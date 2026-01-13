"""Tests for messaging SFTP CSV parsing helpers."""

from utilities import messaging


class DummyTransport:
    def close(self):
        return None


class DummySftp:
    def close(self):
        return None


def test_get_parents_reads_family_rows(monkeypatch):
    def fake_open_sftp():
        return DummyTransport(), DummySftp()

    def fake_read_csv(_sftp, filename):
        if filename == "students.csv":
            return [["fam1", "", "", "", "", "", "student@example.com"]]
        if filename == "families.csv":
            return [["fam1", "", "", "", "", "", "p1@example.com", "", "", "", "", "", "p2@example.com"]]
        return []

    monkeypatch.setattr(messaging, "_open_sftp", fake_open_sftp)
    monkeypatch.setattr(messaging, "_read_remote_csv", fake_read_csv)

    parents = messaging.get_parents("student@example.com")
    assert parents == ["p1@example.com", "p2@example.com"]


def test_get_parents_returns_empty_when_not_found(monkeypatch):
    def fake_open_sftp():
        return DummyTransport(), DummySftp()

    def fake_read_csv(_sftp, filename):
        if filename == "students.csv":
            return [["fam1", "", "", "", "", "", "other@example.com"]]
        if filename == "families.csv":
            return [["fam1", "", "", "", "", "", "p1@example.com"]]
        return []

    monkeypatch.setattr(messaging, "_open_sftp", fake_open_sftp)
    monkeypatch.setattr(messaging, "_read_remote_csv", fake_read_csv)

    parents = messaging.get_parents("student@example.com")
    assert parents == []


def test_get_phone_number_reads_student_row(monkeypatch):
    def fake_open_sftp():
        return DummyTransport(), DummySftp()

    def fake_read_csv(_sftp, filename):
        if filename == "students.csv":
            return [["fam1", "", "", "", "", "5551234567", "student@example.com"]]
        return []

    monkeypatch.setattr(messaging, "_open_sftp", fake_open_sftp)
    monkeypatch.setattr(messaging, "_read_remote_csv", fake_read_csv)

    phone = messaging.get_phone_number("student@example.com")
    assert phone == "5551234567"
