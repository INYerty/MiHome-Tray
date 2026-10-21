# SPDX-License-Identifier: GPL-3.0-or-later
"""Update metadata, trust boundaries, and disk cleanup using fake release bytes."""

from dataclasses import replace
import hashlib
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from app.core import update_checker as checker
from app.core import update_download as download


TAG = "v0.4.2"
NAME = "MiHome-Tray-Setup-0.4.2-x64.exe"
PAYLOAD = b"MZ synthetic installer fixture - never executed"
CHECKSUM = hashlib.sha256(PAYLOAD).hexdigest()


def info():
    return checker.ReleaseInfo(TAG, "https://github.com/INYerty/MiHome-Tray/releases/tag/" + TAG, TAG,
                               checker.release_asset_url(TAG, NAME), NAME,
                               checker.release_asset_url(TAG, "SHA256SUMS.txt"), len(PAYLOAD))


class Response:
    def __init__(self, data=None, chunks=(), status=200, headers=None):
        self.data = data
        self.chunks = chunks
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("simulated HTTP failure")

    def json(self):
        return self.data

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


@pytest.fixture
def release_data():
    return {"tag_name": TAG, "name": "控制台升级", "draft": False, "prerelease": False,
            "html_url": "https://evil.example/metadata-link-is-ignored",
            "assets": [
                {"name": NAME, "size": len(PAYLOAD), "browser_download_url": info().installer_url},
                {"name": "SHA256SUMS.txt", "size": 120, "browser_download_url": info().checksum_url},
                {"name": "MiHome-Tray-portable.zip", "browser_download_url": "https://evil.example/ignored"},
            ]}


def test_latest_release_uses_users_repository_and_exact_versioned_setup(monkeypatch, release_data):
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(data=release_data)
    monkeypatch.setattr(checker.requests, "get", get)
    result = checker.fetch_latest_release()
    assert result.installer_name == NAME and result.size == len(PAYLOAD)
    assert result.installer_url == info().installer_url
    assert result.checksum_url == info().checksum_url
    assert result.url == info().url
    assert calls[0][0] == "https://api.github.com/repos/INYerty/MiHome-Tray/releases/latest"
    assert calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("change", [
    {"prerelease": True}, {"draft": True}, {"tag_name": "v0.4.2-beta"},
    {"tag_name": "../../outside"},
])
def test_non_stable_or_unsafe_release_is_rejected(monkeypatch, release_data, change):
    release_data.update(change)
    monkeypatch.setattr(checker.requests, "get", lambda *args, **kwargs: Response(data=release_data))
    with pytest.raises(RuntimeError):
        checker.fetch_latest_release()


def test_wrong_repository_asset_is_rejected(monkeypatch, release_data):
    release_data["assets"][0]["browser_download_url"] = "https://github.com/other/repo/releases/download/" + TAG + "/" + NAME
    monkeypatch.setattr(checker.requests, "get", lambda *args, **kwargs: Response(data=release_data))
    with pytest.raises(RuntimeError, match="不属于"):
        checker.fetch_latest_release()


def test_missing_or_old_setup_does_not_get_substituted(monkeypatch, release_data):
    release_data["assets"][0]["name"] = "MiHome-Tray-Setup-0.3.2-x64.exe"
    monkeypatch.setattr(checker.requests, "get", lambda *args, **kwargs: Response(data=release_data))
    result = checker.fetch_latest_release()
    assert not result.installer_url and not result.installer_name


@pytest.fixture
def network(monkeypatch, tmp_path):
    responses = [
        Response(chunks=[f"{CHECKSUM}  {NAME}\n".encode()]),
        Response(chunks=[PAYLOAD[:10], PAYLOAD[10:]], headers={"Content-Length": str(len(PAYLOAD))}),
    ]
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return responses.pop(0)
    monkeypatch.setattr(download.requests, "get", get)
    monkeypatch.setattr(download, "data_dir", lambda: tmp_path)
    return responses, calls, tmp_path


def test_download_is_atomic_verified_and_reports_byte_progress(network):
    responses, calls, directory = network
    progress = []
    path = download.download_release(info(), threading.Event(), lambda *item: progress.append(item))
    assert path == directory / "updates" / "0.4.2" / NAME
    assert path.read_bytes() == PAYLOAD
    assert not list(directory.rglob("*.part"))
    assert progress == [(0, len(PAYLOAD)), (10, len(PAYLOAD)), (len(PAYLOAD), len(PAYLOAD))]
    assert [call[0] for call in calls] == [info().checksum_url, info().installer_url]
    assert all(not call[1]["allow_redirects"] for call in calls)


@pytest.mark.parametrize("failure", ["hash", "short", "oversize", "header", "network", "filename", "duplicate"])
def test_invalid_download_never_leaves_an_executable_or_partial_file(network, failure):
    responses, _calls, directory = network
    if failure == "hash":
        responses[1].chunks = [b"X" * len(PAYLOAD)]
    elif failure == "short":
        responses[1].chunks = [PAYLOAD[:-1]]
    elif failure == "oversize":
        responses[1].chunks = [PAYLOAD + b"X"]
    elif failure == "header":
        responses[1].headers = {"Content-Length": "999"}
    elif failure == "network":
        responses[1].chunks = [PAYLOAD[:10], ConnectionError("connection interrupted")]
    elif failure == "filename":
        responses[0].chunks = [f"{CHECKSUM}  ../{NAME}\n".encode()]
    elif failure == "duplicate":
        responses[0].chunks = [(f"{CHECKSUM}  {NAME}\n" * 2).encode()]
    with pytest.raises((RuntimeError, ConnectionError)):
        download.download_release(info(), threading.Event())
    assert not list(directory.rglob("*.exe"))
    assert not list(directory.rglob("*.part"))


def test_cancel_mid_stream_removes_partial_download(network):
    _responses, _calls, directory = network
    cancel = threading.Event()
    def progress(received, total):
        if received:
            cancel.set()
    with pytest.raises(download.UpdateCancelled):
        download.download_release(info(), cancel, progress)
    assert not list(directory.rglob("*.exe")) and not list(directory.rglob("*.part"))


@pytest.mark.parametrize("field,value", [
    ("installer_url", "https://evil.example/file.exe"),
    ("installer_name", "../outside.exe"),
    ("checksum_url", "https://github.com/other/repo/releases/download/v0.4.2/SHA256SUMS.txt"),
    ("checksum_url", ""), ("installer_url", ""), ("size", 0),
])
def test_downloader_revalidates_metadata_before_any_network_request(network, field, value):
    _responses, calls, directory = network
    with pytest.raises(RuntimeError):
        download.download_release(replace(info(), **{field: value}), threading.Event())
    assert calls == [] and not list(directory.iterdir())


def test_redirect_to_arbitrary_domain_is_blocked(network):
    responses, calls, directory = network
    responses[0] = Response(status=302, headers={"Location": "https://evil.example/sums"})
    with pytest.raises(RuntimeError, match="不受信任"):
        download.download_release(info(), threading.Event())
    assert len(calls) == 1 and not list(directory.iterdir())


def test_official_release_cdn_redirect_is_allowed(network):
    responses, calls, _directory = network
    responses.insert(0, Response(status=302, headers={
        "Location": "https://release-assets.githubusercontent.com/github-production-release-asset/file?signature=test"}))
    path = download.download_release(info(), threading.Event())
    assert path.read_bytes() == PAYLOAD
    assert calls[1][0].startswith("https://release-assets.githubusercontent.com/")


def test_downloader_runs_outside_ui_thread_and_emits_verified_path(network):
    app = QApplication.instance() or QApplication([])
    updater = download.UpdateDownloader()
    results = []
    updater.finished.connect(lambda path, error: results.append((path, error)))
    updater.start(info())
    deadline = time.monotonic() + 3
    while not results and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert len(results) == 1 and results[0][1] is None
    assert results[0][0].endswith(NAME) and not updater.running
