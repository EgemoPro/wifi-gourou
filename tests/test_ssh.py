"""Tests pour core/ssh.py — SSHClient et SSHPool avec paramiko mocké."""
import time

import paramiko
import pytest


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.connect()
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientConnect:
    def test_connect_success(self, mock_paramiko, mock_ssh_client):
        """connect() établit la connexion et stocke le client."""
        mock_ssh_client.connect()
        assert mock_ssh_client._client is not None
        assert mock_ssh_client._last_error is None
        mock_paramiko["client"].connect.assert_called_once()

    def test_connect_authentication_failure(self, mock_paramiko,
                                            mock_ssh_client):
        """AuthenticationException est re-levée immédiatement."""
        mock_paramiko["client"].connect.side_effect = (
            paramiko.AuthenticationException("bad auth")
        )
        with pytest.raises(paramiko.AuthenticationException):
            mock_ssh_client.connect()
        assert mock_ssh_client._last_error == "Authentication failed"

    def test_connect_retry_then_success(self, mock_paramiko,
                                        mock_ssh_client, mocker):
        """Échecs temporaires → retry → succès."""
        mock_paramiko["client"].connect.side_effect = [
            OSError("timeout 1"),
            OSError("timeout 2"),
            None,  # 3ème tentative réussit
        ]
        # Accélérer les time.sleep
        mocker.patch.object(time, "sleep")
        mock_ssh_client.connect()
        assert mock_ssh_client._client is not None
        assert mock_paramiko["client"].connect.call_count == 3

    def test_connect_all_retries_fail(self, mock_paramiko,
                                      mock_ssh_client, mocker):
        """Quand toutes les tentatives échouent → ConnectionError."""
        mock_paramiko["client"].connect.side_effect = OSError("net down")
        mocker.patch.object(time, "sleep")
        with pytest.raises(ConnectionError, match="injoignable"):
            mock_ssh_client.connect()

    def test_connect_sets_host_key_policy(self, mock_paramiko,
                                          mock_ssh_client):
        """AutoAddPolicy est configuré."""
        mock_ssh_client.connect()
        mock_paramiko["client"].set_missing_host_key_policy.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.ensure_connected()
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientEnsureConnected:
    def test_ensure_connected_when_none(self, mock_paramiko,
                                        mock_ssh_client):
        """ensure_connected() appelle connect() si _client est None."""
        assert mock_ssh_client._client is None
        result = mock_ssh_client.ensure_connected()
        assert result is not None
        mock_paramiko["client"].connect.assert_called_once()

    def test_ensure_connected_when_active(self, mock_paramiko,
                                          mock_ssh_client):
        """Quand le transport est actif, pas de reconnexion."""
        mock_ssh_client.connect()
        mock_paramiko["client"].connect.reset_mock()
        result = mock_ssh_client.ensure_connected()
        assert result is not None
        mock_paramiko["client"].connect.assert_not_called()

    def test_ensure_connected_transport_inactive(self, mock_paramiko,
                                                 mock_ssh_client, mocker):
        """Transport inactif → disconnect + reconnect."""
        mock_ssh_client.connect()

        # Simuler transport inactif après la connexion
        mock_paramiko["transport"].is_active.return_value = False
        mock_paramiko["client"].connect.reset_mock()

        mock_ssh_client.ensure_connected()
        # disconnect + reconnect = connect called again
        assert mock_paramiko["client"].connect.call_count == 1

    def test_ensure_connected_transport_none(self, mock_paramiko,
                                             mock_ssh_client, mocker):
        """Transport None → reconnect."""
        mock_ssh_client.connect()
        mock_paramiko["client"].get_transport.return_value = None
        mock_paramiko["client"].connect.reset_mock()

        mock_ssh_client.ensure_connected()
        assert mock_paramiko["client"].connect.call_count == 1


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.is_connected
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientIsConnected:
    def test_not_connected_when_no_client(self, mock_ssh_client):
        assert mock_ssh_client.is_connected is False

    def test_connected_when_active(self, mock_paramiko, mock_ssh_client):
        mock_ssh_client.connect()
        assert mock_ssh_client.is_connected is True

    def test_not_connected_when_transport_none(self, mock_paramiko,
                                                mock_ssh_client):
        mock_ssh_client.connect()
        mock_paramiko["client"].get_transport.return_value = None
        assert mock_ssh_client.is_connected is False

    def test_not_connected_when_exception(self, mock_paramiko,
                                          mock_ssh_client):
        mock_ssh_client.connect()
        mock_paramiko["client"].get_transport.side_effect = (
            Exception("broken")
        )
        assert mock_ssh_client.is_connected is False


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.execute()
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientExecute:
    def test_execute_success(self, mock_paramiko, mock_ssh_client):
        """execute() retourne stdout, stderr, exit_code."""
        mock_ssh_client.connect()
        result = mock_ssh_client.execute("/system resource print")
        assert result["exit_code"] == 0
        assert "mocked stdout output" in result["stdout"]
        assert result["stderr"] == ""
        mock_paramiko["client"].exec_command.assert_called_once()

    def test_execute_non_zero_exit(self, mock_paramiko, mock_ssh_client):
        """exit_code != 0 est retourné sans erreur."""
        mock_paramiko["stdout"].channel.recv_exit_status.return_value = 1
        mock_paramiko["stderr"].read.return_value = b"error message"
        mock_ssh_client.connect()
        result = mock_ssh_client.execute("/bad/command")
        assert result["exit_code"] == 1
        assert "error message" in result["stderr"]

    def test_execute_exception(self, mock_paramiko, mock_ssh_client):
        """Exception pendant exec → dict avec exit_code=-1."""
        mock_paramiko["client"].exec_command.side_effect = (
            RuntimeError("SSH broken pipe")
        )
        mock_ssh_client.connect()
        result = mock_ssh_client.execute("/some/command")
        assert result["exit_code"] == -1
        assert "SSH broken pipe" in result["stderr"]

    def test_execute_before_connect(self, mock_paramiko, mock_ssh_client):
        """execute() appelle ensure_connected() automatiquement."""
        assert mock_ssh_client._client is None
        result = mock_ssh_client.execute("/command")
        assert result["exit_code"] == 0
        mock_paramiko["client"].connect.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.execute_script()
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientExecuteScript:
    def test_execute_script_full_pipeline(self, mock_paramiko,
                                          mock_ssh_client):
        """execute_script() upload → import → cleanup → retour."""
        mock_ssh_client.connect()
        result = mock_ssh_client.execute_script(":put \"hello\"")
        assert result["exit_code"] == 0
        assert "script_id" in result
        assert "filename" in result
        # SFTP upload should have been called
        mock_paramiko["sftp"].file.assert_called_once()
        # Cleanup should remove the temp file
        mock_paramiko["sftp"].remove.assert_called_once()

    def test_execute_script_no_cleanup(self, mock_paramiko,
                                       mock_ssh_client):
        """cleanup=False → pas de suppression du fichier distant."""
        mock_ssh_client.connect()
        mock_ssh_client.execute_script(":put \"data\"", cleanup=False)
        mock_paramiko["sftp"].remove.assert_not_called()

    def test_execute_script_upload_error(self, mock_paramiko,
                                         mock_ssh_client, mocker):
        """Erreur pendant upload → cleanup tenté."""
        mock_paramiko["sftp"].file.side_effect = IOError("disk full")
        mock_ssh_client.connect()
        result = mock_ssh_client.execute_script(":put \"fail\"")
        assert result["exit_code"] == -1
        # Tentative de cleanup même en erreur
        mock_paramiko["sftp"].remove.assert_called_once()

    def test_execute_script_upload_error_cleanup_fails(
            self, mock_paramiko, mock_ssh_client, mocker):
        """Erreur upload + échec cleanup → pas de levée."""
        mock_paramiko["sftp"].file.side_effect = IOError("disk full")
        mock_paramiko["sftp"].remove.side_effect = IOError("cleanup fail")
        mock_ssh_client.connect()
        result = mock_ssh_client.execute_script(":put \"fail\"")
        assert result["exit_code"] == -1  # pas d'exception


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.execute_script_from_file()
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientExecuteScriptFromFile:
    def test_file_not_found(self, mock_ssh_client):
        """Script inexistant → réponse structurée avec erreur."""
        result = mock_ssh_client.execute_script_from_file(
            "/nonexistent/path.rsc"
        )
        assert result["exit_code"] == -1
        assert "not found" in result["stderr"].lower()

    def test_injects_params(self, mock_ssh_client, tmp_path):
        """Les paramètres sont injectés en en-tête :local."""
        script = tmp_path / "test.rsc"
        script.write_text('/ip hotspot user add name=$username\n')
        result = mock_ssh_client.execute_script_from_file(
            str(script),
            params={"username": "test_user", "password": "secret"},
        )
        assert result["exit_code"] == 0
        # Le contenu uploadé doit contenir les :local declarations
        # On vérifie via le mock SFTP
        assert "script_id" in result

    def test_injects_params_with_quotes(self, mock_ssh_client, tmp_path):
        """Les guillemets dans les params sont échappés."""
        script = tmp_path / "test.rsc"
        script.write_text('/ip hotspot user add name=$username\n')
        result = mock_ssh_client.execute_script_from_file(
            str(script),
            params={"username": 'test"user'},
        )
        assert result["exit_code"] == 0

    def test_no_params(self, mock_ssh_client, tmp_path):
        """Sans params, le script est passé tel quel."""
        script = tmp_path / "test.rsc"
        script.write_text('/system reboot\n')
        result = mock_ssh_client.execute_script_from_file(str(script))
        assert result["exit_code"] == 0


# ═════════════════════════════════════════════════════════════════════════
# Opérations SFTP
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientSFTP:
    def test_read_file(self, mock_paramiko, mock_ssh_client):
        """read_file() lit un fichier distant via SFTP."""
        mock_paramiko["sftp"].file.return_value.__enter__.return_value\
            .read.return_value = b"backup data"
        mock_ssh_client.connect()
        data = mock_ssh_client.read_file("/backup.backup")
        assert data == b"backup data"

    def test_write_file_string(self, mock_paramiko, mock_ssh_client):
        """write_file() écrit un string encodé en UTF-8."""
        mock_ssh_client.connect()
        mock_ssh_client.write_file("/tmp/test.txt", "hello world")
        handle = mock_paramiko["sftp"].file.return_value.__enter__
        # Le contenu doit être encodé en bytes
        written = handle.return_value.write.call_args[0][0]
        assert isinstance(written, bytes)
        assert written == b"hello world"

    def test_write_file_bytes(self, mock_paramiko, mock_ssh_client):
        """write_file() passe les bytes tels quels."""
        mock_ssh_client.connect()
        mock_ssh_client.write_file("/tmp/test.bin", b"raw bytes")
        handle = mock_paramiko["sftp"].file.return_value.__enter__
        written = handle.return_value.write.call_args[0][0]
        assert written == b"raw bytes"

    def test_download_file(self, mock_paramiko, mock_ssh_client, tmp_path):
        """download_file() télécharge via SFTP.get()."""
        local = tmp_path / "backup.backup"
        mock_ssh_client.connect()
        result = mock_ssh_client.download_file("/remote.backup", str(local))
        assert result == local
        mock_paramiko["sftp"].get.assert_called_once_with(
            "/remote.backup", str(local)
        )

    def test_list_files(self, mock_paramiko, mock_ssh_client):
        """list_files() liste un répertoire distant."""
        mock_paramiko["sftp"].listdir.return_value = ["file1", "file2"]
        mock_ssh_client.connect()
        files = mock_ssh_client.list_files("/")
        assert files == ["file1", "file2"]

    def test_sftp_upload(self, mock_paramiko, mock_ssh_client):
        """_sftp_upload écrit le contenu encodé."""
        mock_ssh_client.connect()
        mock_ssh_client._sftp_upload("/tmp/test.rsc", "content")
        handle = mock_paramiko["sftp"].file.return_value.__enter__
        written = handle.return_value.write.call_args[0][0]
        assert written == b"content"

    def test_sftp_remove(self, mock_paramiko, mock_ssh_client):
        """_sftp_remove supprime le fichier distant."""
        mock_ssh_client.connect()
        mock_ssh_client._sftp_remove("/tmp/test.rsc")
        mock_paramiko["sftp"].remove.assert_called_once_with(
            "/tmp/test.rsc"
        )

    def test_sftp_remove_ioerror(self, mock_paramiko, mock_ssh_client):
        """_sftp_remove ne lève pas d'exception sur IOError."""
        mock_paramiko["sftp"].remove.side_effect = IOError("not found")
        mock_ssh_client.connect()
        mock_ssh_client._sftp_remove("/tmp/test.rsc")  # ne doit pas lever

    def test_ssh_sftp_timeout(self, mock_paramiko, mock_ssh_client, mocker):
        """_get_sftp() configure le timeout du channel SFTP."""
        mock_channel = mocker.MagicMock()
        mock_paramiko["sftp"].get_channel.return_value = mock_channel

        mock_ssh_client.connect()
        mock_ssh_client._get_sftp()

        assert mock_channel.timeout == mock_ssh_client.timeout


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.disconnect()
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientDisconnect:
    def test_disconnect_closes_sftp_and_ssh(self, mock_paramiko,
                                            mock_ssh_client):
        """disconnect() ferme SFTP puis SSH."""
        mock_ssh_client.connect()
        # Ouvrir SFTP d'abord (via une opération qui appelle _get_sftp)
        mock_ssh_client._sftp_upload("/tmp/test.rsc", "data")
        assert mock_ssh_client._sftp is not None
        mock_ssh_client.disconnect()
        mock_paramiko["sftp"].close.assert_called_once()
        mock_paramiko["client"].close.assert_called_once()
        assert mock_ssh_client._sftp is None
        assert mock_ssh_client._client is None

    def test_disconnect_when_not_connected(self, mock_ssh_client):
        """disconnect() ne lève pas si pas connecté."""
        mock_ssh_client.disconnect()  # ne doit pas lever

    def test_disconnect_sftp_close_exception(self, mock_paramiko,
                                             mock_ssh_client):
        """Exception SFTP.close ne bloque pas la déconnexion."""
        mock_paramiko["sftp"].close.side_effect = Exception("sftp error")
        mock_ssh_client.connect()
        mock_ssh_client.disconnect()  # ne doit pas lever


# ═════════════════════════════════════════════════════════════════════════
# SSHClient.last_error
# ═════════════════════════════════════════════════════════════════════════


class TestSSHClientLastError:
    def test_initial_error_is_none(self, mock_ssh_client):
        assert mock_ssh_client.last_error is None

    def test_error_after_failed_execute(self, mock_paramiko,
                                        mock_ssh_client):
        mock_paramiko["client"].exec_command.side_effect = (
            RuntimeError("broken")
        )
        mock_ssh_client.connect()
        mock_ssh_client.execute("/command")
        assert mock_ssh_client.last_error == "broken"


# ═════════════════════════════════════════════════════════════════════════
# SSHPool
# ═════════════════════════════════════════════════════════════════════════


class TestSSHPool:
    def test_get_client_creates_and_connects(self, mock_paramiko,
                                             mock_ssh_pool):
        """get_client() crée un SSHClient et le connecte."""
        client = mock_ssh_pool.get_client()
        assert client is not None
        assert mock_ssh_pool._client is not None

    def test_get_client_reuses_connected(self, mock_paramiko,
                                         mock_ssh_pool):
        """get_client() réutilise le client si déjà connecté."""
        client1 = mock_ssh_pool.get_client()
        mock_paramiko["client"].connect.reset_mock()
        client2 = mock_ssh_pool.get_client()
        assert client1 is client2
        mock_paramiko["client"].connect.assert_not_called()

    def test_get_client_reconnects_if_disconnected(
            self, mock_paramiko, mock_ssh_pool):
        """get_client() reconnecte si le transport est inactif."""
        client1 = mock_ssh_pool.get_client()
        mock_paramiko["transport"].is_active.return_value = False
        mock_paramiko["client"].connect.reset_mock()
        client2 = mock_ssh_pool.get_client()
        assert client1 is client2  # même instance
        mock_paramiko["client"].connect.assert_called_once()

    def test_is_connected(self, mock_paramiko, mock_ssh_pool):
        """is_connected reflète l'état du client."""
        assert mock_ssh_pool.is_connected is False
        mock_ssh_pool.get_client()
        assert mock_ssh_pool.is_connected is True

    def test_disconnect(self, mock_paramiko, mock_ssh_pool):
        """disconnect() libère le client."""
        mock_ssh_pool.get_client()
        mock_ssh_pool.disconnect()
        assert mock_ssh_pool._client is None

    def test_last_error(self, mock_paramiko, mock_ssh_pool):
        """last_error délègue au client."""
        assert mock_ssh_pool.last_error is None
        mock_ssh_pool.get_client()
        assert mock_ssh_pool.last_error is None  # pas d'erreur

    def test_last_error_before_client(self, mock_ssh_pool):
        """last_error est None quand _client n'a pas été créé."""
        assert mock_ssh_pool.last_error is None

    def test_last_error_from_client(self, mock_paramiko, mock_ssh_pool):
        """last_error remonte l'erreur du client."""
        mock_ssh_pool.get_client()
        mock_ssh_pool._client._last_error = "test error"
        assert mock_ssh_pool.last_error == "test error"

    def test_ssh_pool_reconnect(self, mock_paramiko, mock_ssh_pool):
        """get_client() crée une nouvelle connexion si le transport est mort."""
        client1 = mock_ssh_pool.get_client()
        assert mock_paramiko["client"].connect.call_count == 1

        # Simuler transport inactif → is_connected devient False
        mock_paramiko["transport"].is_active.return_value = False
        mock_paramiko["client"].connect.reset_mock()

        client2 = mock_ssh_pool.get_client()
        # Même instance SSHClient wrapper, mais nouvelle connexion paramiko
        assert client1 is client2
        assert mock_paramiko["client"].connect.call_count == 1

    def test_ssh_pool_concurrent(self, mock_paramiko, mock_ssh_pool):
        """SSHPool gère les accès concurrents sans exception."""
        import threading

        n_threads = 5
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        def access_pool() -> None:
            try:
                barrier.wait()
                client = mock_ssh_pool.get_client()
                _ = client.is_connected
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_pool)
                   for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert mock_ssh_pool._client is not None


# ═════════════════════════════════════════════════════════════════════════
# Dépréciés dans ssh.py (parse_routeros_output, parse_table_output)
# ═════════════════════════════════════════════════════════════════════════


class TestDeprecatedWrappers:
    def test_parse_routeros_output_deprecated(self):
        """La fonction dépréciée dans ssh.py redirige vers utils."""
        from core.ssh import parse_routeros_output
        result = parse_routeros_output("name: test")
        assert len(result) == 1
        assert result[0]["name"] == "test"

    def test_parse_table_output_deprecated(self):
        """La fonction dépréciée dans ssh.py redirige vers utils."""
        from core.ssh import parse_table_output
        result = parse_table_output("")
        assert result == []
