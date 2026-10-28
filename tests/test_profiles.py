"""
Tests : profils hotspot (create / update / delete / setup_profile).

Utilisent le VRAI config/commands.json et les VRAIS scripts .rsc ; seuls le routeur
(SSH, REST) et le réseau sont remplacés par des doubles.
"""
import re
from pathlib import Path

import pytest

from core import executor as ex
from core.executor import execute_action
from core.registry import get_script_path, lookup
from core.ssh import SSHClient
from core.validator import ValidationError, validate_params

CONFIG = {"site_id": "SITE_T", "mikrotik_host": "127.0.0.1", "mikrotik_password": "x"}

HOSTILE = [
    'a"; /system reboot; "',
    "a$[/system reboot]",
    "a]; /system reboot; [",
    "a\n/system reboot",
    "a\\",
]


def params_of(action: str, **kw):
    return validate_params(kw, lookup(action))


def render(action: str, params: dict) -> str:
    """Script RouterOS réellement envoyé au routeur pour une action."""
    sent = []
    c = SSHClient.__new__(SSHClient)
    c.execute_script = lambda s, timeout=30, cleanup=True: (
        sent.append(s) or {"stdout": "", "stderr": "", "exit_code": 0})
    d = lookup(action)
    c.execute_script_from_file(get_script_path(d), params=validate_params(params, d))
    return sent[0]


class FakeSSH:
    def __init__(self, exit_code=0, stdout="name=P1"):
        self.cmds, self.exit_code, self.stdout = [], exit_code, stdout

    def execute(self, cmd, timeout=30):
        self.cmds.append(cmd)
        return {"stdout": self.stdout, "stderr": "bad command", "exit_code": self.exit_code}


# ═════════════════════════════════════════════════════════════════════════════
# Validation des paramètres
# ═════════════════════════════════════════════════════════════════════════════

class TestValidation:
    @pytest.mark.parametrize("action,field", [
        ("profile.create", "profileName"), ("profile.update", "name"),
        ("profile.delete", "profileName"), ("hotspot.setup_profile", "profile"),
    ])
    @pytest.mark.parametrize("bad", HOSTILE + ["", " lead", "x" * 33])
    def test_nom_de_profil_hostile_refuse(self, action, field, bad):
        with pytest.raises(ValidationError):
            params_of(action, **{field: bad})

    @pytest.mark.parametrize("good", ["2M-Limit", "default", "Promo 2h", "p1.test_x"])
    def test_noms_legitimes_acceptes(self, good):
        assert params_of("profile.delete", profileName=good)["profileName"] == good

    @pytest.mark.parametrize("bad", ['1h"; /system reboot; "', "1h\n", "abc", "1h $x", "", "1"])
    def test_validity_hostile_refusee(self, bad):
        with pytest.raises(ValidationError):
            params_of("hotspot.setup_profile", profile="p", validity=bad)

    @pytest.mark.parametrize("good", ["1h", "30m", "1d", "1w2d", "90m"])
    def test_validity_legitime(self, good):
        assert params_of("hotspot.setup_profile", profile="p", validity=good)["validity"] == good

    @pytest.mark.parametrize("bad", ['2M"', "1M$[x]", "2M;x", "1M/1M\n"])
    def test_rate_limit_hostile_refuse(self, bad):
        for action, kw in (("profile.create", {"profileName": "p"}), ("profile.update", {"name": "p"})):
            with pytest.raises(ValidationError):
                params_of(action, rate_limit=bad, **kw)

    @pytest.mark.parametrize("good", ["1M/1M", "2M/2M", "512k/1M", "1M/1M 2M/2M 1M/1M 10/10"])
    def test_rate_limit_legitime(self, good):
        assert params_of("profile.create", profileName="p", rate_limit=good)["rate_limit"] == good

    def test_lock_mac_oui_non_seulement(self):
        with pytest.raises(ValidationError):
            params_of("hotspot.setup_profile", profile="p", lock_mac="yes; /x")
        assert params_of("hotspot.setup_profile", profile="p", lock_mac="yes")["lock_mac"] == "yes"

    def test_shared_users_borne(self):
        with pytest.raises(ValidationError):
            params_of("profile.create", profileName="p", shared_users=0)

    @pytest.mark.parametrize("bad", ["1h x", "xh", "1h;"])
    def test_timeouts_invalides(self, bad):
        with pytest.raises(ValidationError):
            params_of("profile.create", profileName="p", session_timeout=bad)


# ═════════════════════════════════════════════════════════════════════════════
# profile.create
# ═════════════════════════════════════════════════════════════════════════════

class TestCreateScript:
    def test_timeouts_appliques(self):
        s = render("profile.create", {"profileName": "P1", "session_timeout": "1h", "idle_timeout": "5m"})
        assert "session-timeout=$sessionTimeout" in s
        assert "idle-timeout=$idleTimeout" in s
        assert ':local sessionTimeout "1h"' in s and ':local idleTimeout "5m"' in s

    def test_data_limit_refuse_au_lieu_d_etre_ignore(self):
        s = render("profile.create", {"profileName": "P1", "data_limit": "500M"})
        body = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))
        # le refus précède toute création
        assert body.index("data_limit unsupported") < body.index("user profile add")


class TestDeleteScript:
    def test_default_protege_avant_toute_suppression(self):
        s = render("profile.delete", {"profileName": "default"})
        body = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))
        assert body.index('$profileName = "default"') < body.index("hotspot user remove")


# ═════════════════════════════════════════════════════════════════════════════
# profile.update
# ═════════════════════════════════════════════════════════════════════════════

class TestUpdate:
    def test_cible_explicite_et_pas_de_renommage(self):
        s = FakeSSH()
        r = ex._handler_update_profile(s, CONFIG, {"name": "P1", "rate_limit": "2M/2M", "shared_users": 2})
        cmd = s.cmds[-1]
        assert r["status"] == "updated"
        assert '[find where name="P1"]' in cmd
        assert 'set name=' not in cmd and ' name="P1" ' not in cmd.replace('[find where name="P1"]', "")
        assert 'rate-limit="2M/2M"' in cmd and "shared-users=2" in cmd

    def test_echec_routeur_n_est_plus_masque(self):
        class Failing(FakeSSH):
            def execute(self, cmd, timeout=30):
                self.cmds.append(cmd)
                if "print" in cmd:
                    return {"stdout": "name=P1", "stderr": "", "exit_code": 0}
                return {"stdout": "", "stderr": "bad command name", "exit_code": 1}
        r = ex._handler_update_profile(Failing(), CONFIG, {"name": "P1", "rate_limit": "2M/2M"})
        assert r["status"] == "error" and "bad command" in r["error"]

    def test_profil_absent(self):
        r = ex._handler_update_profile(FakeSSH(stdout=""), CONFIG, {"name": "nope", "rate_limit": "1M/1M"})
        assert r["status"] == "not_found"

    def test_rien_a_modifier(self):
        s = FakeSSH()
        assert ex._handler_update_profile(s, CONFIG, {"name": "P1"})["status"] == "unchanged"
        assert not any("set" in c for c in s.cmds)

    def test_data_limit_refuse_sans_toucher_le_routeur(self):
        s = FakeSSH()
        r = ex._handler_update_profile(s, CONFIG, {"name": "P1", "data_limit": "1G"})
        assert r["status"] == "error" and s.cmds == []

    @pytest.mark.parametrize("bad", HOSTILE)
    def test_valeurs_hostiles_neutralisees_meme_sans_validateur(self, bad):
        s = FakeSSH()
        ex._handler_update_profile(s, CONFIG, {"name": "P1", "rate_limit": bad})
        cmd = s.cmds[-1]
        # aucun guillemet / $ / [ ] non échappé dans la valeur injectée
        value = re.search(r'rate-limit="(.*)"$', cmd, re.S).group(1)
        assert not re.search(r'(?<!\\)["$\[\]]', value.replace("\\\\", ""))


class TestSanitize:
    def test_caracteres_speciaux_echappes(self):
        assert ex._sanitize_ros_param('a"b$c[d]e\\f') == 'a\\"b\\$c\\[d\\]e\\\\f'

    def test_troncature_avant_echappement(self):
        out = ex._sanitize_ros_param('"' * 100, 10)
        assert out == '\\"' * 10


# ═════════════════════════════════════════════════════════════════════════════
# Scripts générés (exécutés ensuite par le routeur)
# ═════════════════════════════════════════════════════════════════════════════

class TestGeneratedScripts:
    @pytest.mark.parametrize("bad", ['1h"; /system reboot; "', "1h\n/x", "x", ""])
    def test_onlogin_refuse_validity_hostile(self, bad):
        with pytest.raises(ValueError):
            ex._generate_onlogin_script(bad)

    @pytest.mark.parametrize("bad", HOSTILE + [""])
    def test_cleanup_refuse_nom_hostile(self, bad):
        with pytest.raises(ValueError):
            ex._generate_cleanup_script(bad)

    def test_scripts_legitimes_inchanges(self):
        on = ex._generate_onlogin_script("1d")
        assert 'interval="1d"' in on and "# WIFIZONE on-login v2" in on
        assert 'profile="2M-Limit"' in ex._generate_cleanup_script("2M-Limit")

    def test_lock_mac_utilise_la_variable_avec_tiret_entre_guillemets(self):
        assert ':local mac $"mac-address";' in ex._generate_onlogin_script("1h", True)


# ═════════════════════════════════════════════════════════════════════════════
# Lecture des résultats de script
# ═════════════════════════════════════════════════════════════════════════════

def run_script_with_output(out: str):
    ssh = type("S", (), {"execute_script_from_file":
                         lambda self, **k: {"stdout": out, "stderr": "", "exit_code": 0}})()
    return ex._execute_routeros_script(ssh, lookup("profile.create"), {})


class TestResultParsing:
    def test_profil_existant_est_une_erreur(self):
        r = run_script_with_output("PROFILE_ALREADY_EXISTS")
        assert r["status"] == "already_exists" and "error" in r

    def test_profil_introuvable_est_une_erreur(self):
        r = run_script_with_output("PROFILE_NOT_FOUND")
        assert r["status"] == "not_found" and "error" in r

    def test_nom_de_profil_contenant_error_n_est_pas_une_erreur(self):
        r = run_script_with_output("PROFILE_CREATED\nprofile_name=error-test\nrate_limit=1M/1M")
        assert r["status"] == "profile_created" and "error" not in r

    def test_liste_avec_noms_pieges(self):
        r = run_script_with_output("profile_0_name=Not_Found_Promo\nprofile_1_name=already\nprofiles_total=2")
        assert "error" not in r

    def test_suppression_reussie(self):
        assert run_script_with_output("removed_users=3\nPROFILE_DELETED\nprofile_name=x")["status"] == "profile_deleted"

    def test_erreur_explicite_conservee(self):
        r = run_script_with_output("ERROR: le profil default ne peut pas etre supprime")
        assert "error" in r


class TestAutoHook:
    """setup_profile ne doit se déclencher qu'après une VRAIE création."""

    def run(self, monkeypatch, output):
        called = []
        monkeypatch.setattr(ex, "_execute_routeros_script", lambda *a, **k: output)
        monkeypatch.setattr(ex, "_handler_setup_profile",
                            lambda ssh, cfg, p: called.append(p) or {"status": "ok"})
        pool = type("P", (), {"get_client": lambda self: object()})()
        execute_action(pool, CONFIG, "profile.create", {"profileName": "P1"})
        return called

    def test_apres_creation(self, monkeypatch):
        assert self.run(monkeypatch, {"status": "profile_created"}) == [{"profile": "P1"}]

    def test_pas_sur_un_profil_existant(self, monkeypatch):
        assert self.run(monkeypatch, {"status": "already_exists", "error": "x"}) == []

    def test_pas_sur_une_erreur(self, monkeypatch):
        assert self.run(monkeypatch, {"status": "error", "error": "x"}) == []


# ═════════════════════════════════════════════════════════════════════════════
# setup_profile / REST
# ═════════════════════════════════════════════════════════════════════════════

class TestSetupProfileAndRest:
    def test_entrees_invalides_refusees_sans_appel_reseau(self, monkeypatch):
        monkeypatch.setattr(ex, "_rest_api_call",
                            lambda *a, **k: pytest.fail("appel REST inattendu"))
        r = ex._handler_setup_profile(None, CONFIG, {"profile": "p", "validity": '1h"; /x; "'})
        assert r["status"] == "error"
        r = ex._handler_setup_profile(None, CONFIG, {"profile": "../x", "validity": "1h"})
        assert r["status"] == "error"

    def _capture(self, monkeypatch, config):
        seen = {}

        class Resp:
            status_code, text = 200, "[]"
            def raise_for_status(self): pass
            def json(self): return []

        def fake_request(method, url, **kw):
            seen.update(url=url, verify=kw.get("verify"))
            return Resp()
        monkeypatch.setattr(ex.requests, "request", fake_request)
        ex._rest_api_get(config, "system/identity")
        return seen

    def test_schema_http_par_defaut(self, monkeypatch):
        seen = self._capture(monkeypatch, {**CONFIG, "mikrotik_rest_port": 8080})
        assert seen["url"] == "http://127.0.0.1:8080/rest/system/identity"

    def test_schema_https_configurable(self, monkeypatch):
        seen = self._capture(monkeypatch, {**CONFIG, "mikrotik_rest_port": 8443, "mikrotik_rest_scheme": "https"})
        assert seen["url"].startswith("https://127.0.0.1:8443/") and seen["verify"] is False

    @pytest.mark.parametrize("scheme,service", [("http", "www"), ("https", "www-ssl")])
    def test_auto_init_active_le_service_qui_correspond_au_schema(self, monkeypatch, scheme, service):
        def boom(*a, **k):
            raise ConnectionError("REST inactif")
        monkeypatch.setattr(ex, "_rest_api_get", boom)
        s = FakeSSH(stdout="")
        s.exit_code = 1  # l'activation « échoue » : on veut seulement voir la commande
        ex.auto_init_router(s, {**CONFIG, "mikrotik_rest_port": 8080, "mikrotik_rest_scheme": scheme})
        assert any(c.startswith(f"/ip service set {service} ") for c in s.cmds)
        assert not any(c.startswith("/ip service set www-ssl ") for c in s.cmds if service == "www")

    def test_nom_de_profil_encode_dans_l_url(self, monkeypatch):
        urls = []
        monkeypatch.setattr(ex, "_rest_api_get", lambda cfg, path, **k: urls.append(path) or [])
        ex._handler_setup_profile(None, CONFIG, {"profile": "Promo 2h", "validity": "1h"})
        assert urls[0] == "ip/hotspot/user/profile/Promo%202h"


# ═════════════════════════════════════════════════════════════════════════════
# Déploiement container : l'agent doit pouvoir joindre l'API REST
# ═════════════════════════════════════════════════════════════════════════════

class TestContainerScript:
    rsc = (Path(__file__).resolve().parent.parent / "deploy/mikrotik/wifizone-container.rsc").read_text(encoding="utf-8")

    def test_pare_feu_ouvre_le_port_rest_a_l_agent_seulement(self):
        assert re.search(r"dst-port=8080 src-address=\$agIp", self.rsc)

    def test_politique_rest_api_ajoutee_a_part(self):
        # séparée du `group add` : une version sans cette politique ne doit pas empêcher la création du groupe
        assert "policy=read,write,api,ssh,password,test comment" in self.rsc
        assert "test,rest-api" in self.rsc

    def test_service_www_limite_a_l_agent(self):
        assert '/ip service set www disabled=no port=8080 address=($agIp . "/32")' in self.rsc
