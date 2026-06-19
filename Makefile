.PHONY: help setup test run debug install-service start-service stop-service status logs clean uninstall

help:
	@echo "🔧 WIFIZONE Agent — Commandes disponibles"
	@echo ""
	@echo "Configuration :"
	@echo "  make setup              Configuration interactive (.env)"
	@echo "  make test               Tests de connectivité"
	@echo ""
	@echo "Développement :"
	@echo "  make install-deps       Installer dépendances Python"
	@echo "  make run                Démarrer l'agent (mode dev)"
	@echo "  make debug              Démarrer en DEBUG (verbose)"
	@echo ""
	@echo "Production (systemd) :"
	@echo "  make install-service    Installer le service systemd"
	@echo "  make start-service      Démarrer le service"
	@echo "  make stop-service       Arrêter le service"
	@echo "  make status             État du service"
	@echo "  make logs               Afficher les logs en temps réel"
	@echo ""
	@echo "Maintenance :"
	@echo "  make clean              Nettoyer (cache, logs)"
	@echo "  make uninstall          Désinstaller complètement (service + fichiers)"
	@echo ""

setup:
	source venv/bin/activate && python setup.py

test:
	source venv/bin/activate && python test.py

install-deps:
	source venv/bin/activate && pip install -r requirements.txt

run:
	source venv/bin/activate && python main.py

debug:
	source venv/bin/activate && LOG_LEVEL=DEBUG python main.py

install-service:
	@echo "Installation du service systemd..."
	sudo cp wifizone-agent.service /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable wifizone-agent
	@echo "✓ Service installé et activé"

start-service:
	sudo systemctl start wifizone-agent
	@sleep 1
	@sudo systemctl status wifizone-agent

stop-service:
	sudo systemctl stop wifizone-agent

status:
	sudo systemctl status wifizone-agent

logs:
	sudo journalctl -u wifizone-agent -f

clean:
	rm -rf __pycache__ *.pyc
	rm -rf .pytest_cache
	@echo "✓ Cache nettoyé"

uninstall:
	@echo "🔄 Désinstallation de WIFIZONE Agent..."
	@echo ""
	@echo "⚠  Cette action va :"
	@echo "   • Arrêter et désactiver le service systemd"
	@echo "   • Supprimer /etc/systemd/system/wifizone-agent.service"
	@echo "   • Supprimer les bases SQLite (*.db)"
	@echo "   • Supprimer l'environnement virtuel (venv/)"
	@echo "   • Supprimer les caches et logs"
	@echo ""
	@read -p "Continuer ? (y/N) " confirm; \
	if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then \
		echo "Annulé."; exit 0; \
	fi
	@echo ""
	@echo "■ Arrêt du service..."
	-sudo systemctl stop wifizone-agent 2>/dev/null || true
	-sudo systemctl disable wifizone-agent 2>/dev/null || true
	@echo "✓ Service arrêté et désactivé"
	@echo ""
	@echo "■ Suppression du fichier service..."
	-sudo rm -f /etc/systemd/system/wifizone-agent.service
	-sudo systemctl daemon-reload
	@echo "✓ Fichier service supprimé"
	@echo ""
	@echo "■ Nettoyage des bases de données..."
	rm -f *.db core/*.db workers/*.db
	@echo "✓ Bases SQLite supprimées"
	@echo ""
	@echo "■ Nettoyage de l'environnement virtuel..."
	rm -rf venv/
	@echo "✓ Environnement virtuel supprimé"
	@echo ""
	@echo "■ Nettoyage des caches..."
	rm -rf __pycache__ *.pyc .pytest_cache
	rm -rf logs/ backups/ vouchers/
	@echo "✓ Caches et données supprimés"
	@echo ""
	@echo "✅ Désinstallation terminée."
	@echo ""
	@echo "Pour supprimer complètement le répertoire :"
	@echo "  rm -rf $$(pwd)"
	@echo ""

.DEFAULT_GOAL := help
