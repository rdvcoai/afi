#!/bin/bash
# Script para ejecutar auditoría completa y apagar sistema

echo "🌙 Iniciando auditoría nocturna..."
cd ~/AFIV1

# Ejecutar auditoría completa (puede tardar horas)
docker compose run --rm -e AUDIT_DAYS=365 afi-core python /app/full_audit.py

# Al terminar, apagar todo
echo "🛑 Auditoría completada. Apagando sistema..."
docker compose down

echo "✅ Sistema apagado. Resultados en data/auditoria_*.json"
echo "💤 Listo para mañana."
