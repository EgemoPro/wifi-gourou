"""
core/ssh.py — Connexion SSH Paramiko vers MikroTik
Supporte exécution directe et import de scripts .rsc
Toutes les opérations I/O sont synchrones (bloquantes).
Les wrappers async sont dans executor.py.

Pipeline d'exécution de script :
  1. Générer contenu .rsc (:local variables injectées)
  2. SFTP upload vers /tmp/wifizone_<id>.rsc
  3. /import file-name=...
  4. Lire stdout (et fichier de log si besoin)
  5. Nettoyer le fichier temporaire
  6. Retourner output structuré
"""
import time
import random
import uuid
import logging
from typing import Optional, Any
from pathlib import Path

import paramiko

logger = logging.getLogger("ssh")

# Délais entre tentatives (secondes) — identique à l'ancien mikrotik.py
RETRY_DELAYS = [5, 15, 30, 60, 120]

# Répertoire temporaire côté MikroTik pour upload des scripts
# RouterOS a un filesystem plat — utiliser "" pour la racine
MIKROTIK_TMP = ""


def parse_routeros_output(output: str, key_field: str = "name") -> list[dict[str, str]]:
    """
    DÉPRÉCIÉ : Déplacé vers core.utils.
    Conservé pour rétrocompatibilité.
    """
    from core.utils import parse_routeros_output as _new_parse
    return _new_parse(output, key_field)


def parse_table_output(output: str) -> list[dict[str, str]]:
    """
    DÉPRÉCIÉ : Déplacé vers core.utils.
    Conservé pour rétrocompatibilité.
    """
    from core.utils import parse_table_output as _new_parse
    return _new_parse(output)


# ── Classe de connexion SSH ────────────────────────────────────────────────────


class SSHClient:
    """Wraps a single Paramiko SSH connection to a MikroTik router."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "admin",
        password: str = "",
        timeout: int = 15,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None
        self._last_error: Optional[str] = None

    # ── Connexion ──────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Établit la connexion SSH avec backoff exponentiel + jitter."""
        for attempt, delay in enumerate(RETRY_DELAYS, start=1):
            try:
                logger.info(
                    f"SSH {self.host}:{self.port} "
                    f"(tentative {attempt}/{len(RETRY_DELAYS)})"
                )
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=self.timeout,
                    banner_timeout=self.timeout,
                    auth_timeout=self.timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
                self._client = client
                self._last_error = None
                logger.info(f"✅ SSH connecté à {self.host}")
                return
            except paramiko.AuthenticationException:
                self._last_error = "Authentication failed"
                logger.error(f"❌ SSH auth échouée sur {self.host}")
                raise
            except Exception as e:
                self._last_error = str(e)
                if attempt < len(RETRY_DELAYS):
                    jitter = delay * 0.2 * random.uniform(-1, 1)
                    wait = max(1, delay + jitter)
                    logger.warning(
                        f"SSH échec ({e}) — retry dans {wait:.0f}s"
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"❌ SSH {self.host} injoignable "
                        f"après {len(RETRY_DELAYS)} tentatives"
                    )
                    raise ConnectionError(
                        f"SSH {self.host} injoignable : {e}"
                    )

    def ensure_connected(self) -> paramiko.SSHClient:
        """Retourne le client SSH, reconnecte si nécessaire."""
        if self._client is None:
            self.connect()
        else:
            try:
                transport = self._client.get_transport()
                if transport is None or not transport.is_active():
                    logger.info("SSH transport inactif — reconnexion")
                    self.disconnect()
                    self.connect()
            except Exception:
                self.disconnect()
                self.connect()
        return self._client  # type: ignore[return-value]

    @property
    def is_connected(self) -> bool:
        if self._client is None:
            return False
        try:
            t = self._client.get_transport()
            return t is not None and t.is_active()
        except Exception:
            return False

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ── Exécution de commande directe ──────────────────────────────────────────

    def execute(self, command: str, timeout: int = 30) -> dict[str, Any]:
        """
        Exécute une commande RouterOS directement via SSH.
        Retourne {stdout, stderr, exit_code}.

        Utile pour les lectures rapides (metrics, clients, health).
        Utilise transport.open_session() + chan.recv() au lieu de
        exec_command() pour capturer correctement la sortie /import
        sur RouterOS (ChannelFile.read() ne fonctionne pas).
        """
        client = self.ensure_connected()
        logger.debug(f"SSH exec: {command[:120]}")
        try:
            transport = client.get_transport()
            if not transport:
                return {"stdout": "", "stderr": "No transport", "exit_code": -1}

            chan = transport.open_session()
            chan.settimeout(timeout)
            chan.exec_command(command)

            stdout_bytes = b""
            stderr_bytes = b""
            import time
            deadline = time.time() + timeout

            while time.time() < deadline:
                # Drain les données disponibles avant toute vérification
                drained = False
                while chan.recv_ready():
                    data = chan.recv(65536)
                    if data:
                        stdout_bytes += data
                        drained = True
                while chan.recv_stderr_ready():
                    data = chan.recv_stderr(65536)
                    if data:
                        stderr_bytes += data
                        drained = True

                if chan.exit_status_ready():
                    # Drain final avant de sortir
                    while chan.recv_ready():
                        stdout_bytes += chan.recv(65536)
                    while chan.recv_stderr_ready():
                        stderr_bytes += chan.recv_stderr(65536)
                    break

                if not drained:
                    time.sleep(0.05)

            exit_code = chan.recv_exit_status()
            chan.close()

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            result = {
                "stdout": stdout.strip(),
                "stderr": stderr.strip(),
                "exit_code": exit_code,
            }

            if exit_code != 0:
                logger.warning(
                    f"SSH command exit={exit_code}: "
                    f"{stderr.strip() or stdout.strip()[:200]}"
                )

            return result

        except Exception as e:
            self._last_error = str(e)
            logger.error(f"SSH execute error: {e}")
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    # ── Exécution de script .rsc (upload + import) ────────────────────────────

    def execute_script(
        self,
        script_content: str,
        timeout: int = 30,
        cleanup: bool = True,
    ) -> dict[str, Any]:
        """
        Pipeline complet :
          1. Génère un nom de fichier unique
          2. Upload le script .rsc sur le MikroTik
          3. Exécute /import file-name=...
          4. Capture la sortie
          5. Nettoie le fichier temporaire
          6. Retourne {stdout, stderr, exit_code, filename}

        C'est le moteur principal d'exécution d'actions.
        """
        script_id = uuid.uuid4().hex[:12]
        remote_path = f"{MIKROTIK_TMP}/wf_{script_id}.rsc"

        try:
            # Upload
            self._sftp_upload(remote_path, script_content)
            logger.debug(f"Script uploadé : {remote_path}")

            # Import
            import_cmd = f"/import file-name={remote_path}"
            result = self.execute(import_cmd, timeout=timeout)

            # Ajouter le nom du fichaire au résultat
            result["filename"] = remote_path
            result["script_id"] = script_id

            # Cleanup
            if cleanup and result.get("exit_code", -1) != -1:
                self._sftp_remove(remote_path)

            return result

        except Exception as e:
            self._last_error = str(e)
            logger.error(f"execute_script error: {e}")
            # Tentative de cleanup même en erreur
            if cleanup:
                try:
                    self._sftp_remove(remote_path)
                except Exception:
                    pass
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "filename": remote_path,
                "script_id": script_id,
            }

    @staticmethod
    def _sanitize_ros_varname(name: str) -> str:
        """
        Convertit un nom de paramètre Python (ex: 'rate_limit')
        en nom de variable RouterOS compatible (ex: 'rateLimit').

        RouterOS n'accepte pas les underscore, tirets, ou points
        dans les noms de variables. On convertit snake_case → camelCase.
        Et on supprime les caractères interdits.
        """
        # snake_case → camelCase
        parts = name.replace("-", "_").split("_")
        result = parts[0] + "".join(p.capitalize() for p in parts[1:])
        # Ne garder que les caractères autorisés
        return "".join(c for c in result if c.isalnum())

    def execute_script_from_file(
        self,
        local_path: str | Path,
        params: dict[str, str] | None = None,
        timeout: int = 30,
        cleanup: bool = True,
    ) -> dict[str, Any]:
        """
        Charge un fichier .rsc local, injecte les paramètres,
        puis exécute via execute_script().

        Injection sécurisée : génère :local variable "valeur"
        pour chaque paramètre. Pas de replace() dangereux.
        Les noms de variables sont sanitizés (snake_case → camelCase)
        car RouterOS n'accepte pas les underscore.
        """
        local_path = Path(local_path)
        if not local_path.is_file():
            return {
                "stdout": "",
                "stderr": f"Script not found: {local_path.name}",
                "exit_code": -1,
                "filename": local_path.name,
                "script_id": "",
            }

        raw = local_path.read_text(encoding="utf-8")

        if params:
            # Préfixer le script avec les :local declarations
            header_lines = []
            for key, value in params.items():
                safe_val = str(value).replace('"', '\\"')
                safe_key = self._sanitize_ros_varname(key)
                header_lines.append(f':local {safe_key} "{safe_val}"')
            script_content = "\n".join(header_lines) + "\n\n" + raw
        else:
            script_content = raw

        return self.execute_script(script_content, timeout=timeout, cleanup=cleanup)

    # ── Opérations SFTP ──────────────────────────────────────────────────────

    def _get_sftp(self) -> paramiko.SFTPClient:
        """Retourne un client SFTP (ouvert si nécessaire)."""
        if self._sftp is None or self._sftp.sock is None:
            client = self.ensure_connected()
            self._sftp = client.open_sftp()
            # Appliquer le timeout aux opérations SFTP
            try:
                chan = self._sftp.get_channel()
                if chan:
                    chan.timeout = self.timeout
            except Exception:
                pass  # timeout non critique
        return self._sftp

    def _sftp_upload(self, remote_path: str, content: str) -> None:
        """Upload d'un fichier texte via SFTP."""
        sftp = self._get_sftp()
        with sftp.file(remote_path, "w") as f:
            f.write(content.encode("utf-8"))

    def _sftp_remove(self, remote_path: str) -> None:
        """Supprime un fichier distant via SFTP."""
        try:
            sftp = self._get_sftp()
            sftp.remove(remote_path)
            logger.debug(f"Fichier supprimé : {remote_path}")
        except (IOError, OSError) as e:
            logger.warning(f"Nettoyage fichier ignoré ({remote_path}): {e}")

    def read_file(self, remote_path: str) -> bytes:
        """Lit un fichier distant via SFTP (ex: backup)."""
        sftp = self._get_sftp()
        with sftp.file(remote_path, "rb") as f:
            return f.read()

    def write_file(self, remote_path: str, content: bytes | str) -> None:
        """Écrit un fichier distant via SFTP."""
        sftp = self._get_sftp()
        if isinstance(content, str):
            content = content.encode("utf-8")
        with sftp.file(remote_path, "wb") as f:
            f.write(content)

    def download_file(self, remote_path: str, local_path: str | Path) -> Path:
        """Télécharge un fichier distant via SFTP."""
        local_path = Path(local_path)
        sftp = self._get_sftp()
        sftp.get(remote_path, str(local_path))
        logger.info(f"Téléchargé : {remote_path} → {local_path}")
        return local_path

    def list_files(self, remote_dir: str = "/") -> list[str]:
        """Liste les fichiers d'un répertoire distant."""
        sftp = self._get_sftp()
        return sftp.listdir(remote_dir)

    # ── Nettoyage ────────────────────────────────────────────────────────────

    def disconnect(self) -> None:
        """Ferme connexion SSH et SFTP."""
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        finally:
            self._sftp = None

        try:
            if self._client:
                self._client.close()
        except Exception:
            pass
        finally:
            self._client = None

        logger.debug("SSH déconnecté")


# ── Pool de connexions ─────────────────────────────────────────────────────────


class SSHPool:
    """
    Pool de connexions SSH.

    Pour l'instant : connexion unique qui se reconfigure automatiquement.
    Pour du multi-thread, utiliser plusieurs SSHPool ou un pool dédié.
    """

    def __init__(self, config: dict):
        self.host = config["mikrotik_host"]
        self.port = int(config.get("mikrotik_ssh_port", 22))
        self.user = config.get("mikrotik_user", "admin")
        self.password = config["mikrotik_password"]
        self.timeout = int(config.get("ssh_timeout", 15))
        self._client: Optional[SSHClient] = None
        self._last_error: Optional[str] = None

    def get_client(self) -> SSHClient:
        """Retourne un client SSH connecté (reconnecte si nécessaire)."""
        if self._client is None:
            self._client = SSHClient(
                host=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=self.timeout,
            )
        if not self._client.is_connected:
            self._client.disconnect()
            self._client.connect()
        return self._client

    @property
    def is_connected(self) -> bool:
        if self._client is None:
            return False
        return self._client.is_connected

    @property
    def last_error(self) -> Optional[str]:
        if self._client:
            return self._client.last_error
        return self._last_error

    def disconnect(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client = None
