"""Tests pour core/registry.py — sans MikroTik."""
import sys
sys.path.insert(0, ".")

from core.registry import lookup, list_actions, resolve_name, get_script_path


class TestRegistry:
    """Tests sur le registre d'actions (chargé depuis config/commands.json)."""

    def test_lookup_existing_action(self):
        # lookup retourne le dict de l'action (sans clé 'name' explicite)
        action = lookup("hotspot.create_user")
        assert action is not None
        assert "description" in action
        assert "params" in action
        assert isinstance(action["params"], list)

    def test_lookup_nonexistent_action(self):
        action = lookup("nonexistent.action")
        assert action is None

    def test_list_actions_returns_dict(self):
        actions = list_actions()
        assert isinstance(actions, dict)
        assert len(actions) > 0
        # Vérifie quelques actions connues
        assert "hotspot.create_user" in actions
        assert "router.health" in actions

    def test_list_actions_has_required_fields(self):
        actions = list_actions()
        for name, info in actions.items():
            assert "description" in info, f"Action {name} missing description"
            assert "danger" in info, f"Action {name} missing danger"
            assert "params" in info, f"Action {name} missing params"
            assert isinstance(info["params"], list)

    def test_resolve_name_with_alias(self):
        # create_user est un alias de hotspot.create_user
        resolved = resolve_name("create_user")
        assert resolved == "hotspot.create_user"

    def test_resolve_name_already_canonical(self):
        resolved = resolve_name("hotspot.create_user")
        assert resolved == "hotspot.create_user"

    def test_resolve_name_unknown(self):
        resolved = resolve_name("unknown.command")
        assert resolved is None

    def test_get_script_path_routeros_action(self):
        action = lookup("hotspot.create_user")
        assert action is not None
        path = get_script_path(action)
        assert path is not None
        assert str(path).endswith(".rsc")
        assert path.is_file()

    def test_get_script_path_python_action(self):
        # Les actions python n'ont pas de script
        action = lookup("hotspot.vouchers")
        assert action is not None
        assert action.get("type") == "python"
        path = get_script_path(action)
        assert path is None

    def test_diagnostics_actions_exist(self):
        actions = list_actions()
        for diag in ["router.health", "router.info",
                     "network.interfaces", "system.scheduler_list"]:
            assert diag in actions, f"Missing diagnostic action: {diag}"

    def test_lookup_returns_full_action_def(self):
        """Le lookup retourne des infos plus riches que list_actions()."""
        action = lookup("hotspot.create_user")
        assert action is not None
        assert "script" in action or action.get("type") == "python"
        assert "params" in action
        assert "description" in action
        # Le type devrait être routeros ou python
        assert action.get("type") in ("routeros", "python")

    def test_all_actions_have_type(self):
        """Toutes les actions doivent avoir un type valide."""
        actions = list_actions()
        for name in actions:
            action = lookup(name)
            assert action is not None
            assert action.get("type") in ("routeros", "python"), (
                f"Action {name} invalid type: {action.get('type')}"
            )
