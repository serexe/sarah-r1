"""Tests never inherit integration credentials or allow non-loopback sockets."""
import os
import socket
import ipaddress
import pytest

# Apply before test module imports. Do not load or inspect credential files.
for name in list(os.environ):
    if name.startswith(('R1_', 'SIYUAN_', 'MATON_')):
        os.environ.pop(name, None)


@pytest.fixture(autouse=True)
def local_sockets_only(monkeypatch):
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def check(address):
        if isinstance(address, tuple):
            host = address[0]
            if host == 'localhost':
                return
            try:
                if ipaddress.ip_address(host).is_loopback:
                    return
            except ValueError:
                pass
            raise AssertionError('offline tests forbid non-loopback sockets')

    def connect(sock, address):
        check(address)
        return original(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_ex(sock, address)

    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', connect_ex)
