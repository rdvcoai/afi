# 📋 INSTRUCCIONES DETALLADAS - AUDITORÍA DE CORREOS

## 🎯 OBJETIVO
Analizar TODOS los correos (leídos y no leídos) del último año para identificar:
- 🏦 Cuentas bancarias
- 💳 Pasivos (deudas, préstamos, tarjetas)
- 💰 Activos (inversiones, propiedades)
- 🔄 Suscripciones y gastos recurrentes
- 📊 Transacciones financieras

---

## 📂 ARCHIVOS CLAVE

### Script de Auditoría
```
~/AFIV1/afi-core/full_audit.py
```
- Lee TODOS los correos desde hace 365 días
- Usa Ollama (Qwen 14B) para análisis con IA
- Guarda resultados en `/data/auditoria_YYYYMMDD_HHMMSS.json`

### Configuración
```
~/AFIV1/.env
```
Variables importantes:
- `EMAIL_USER`: Tu cuenta de Gmail
- `EMAIL_PASS`: App Password de Google
- `OLLAMA_MODEL`: Modelo IA (qwen2.5:14b)
- `AUDIT_DAYS`: Días hacia atrás (default: 365)

---

## 🚀 PROCESO MANUAL PASO A PASO

### PASO 1: Revisar el código del auditor
```bash
# Ver el script completo
cat ~/AFIV1/afi-core/full_audit.py

# O editarlo si necesitas ajustes
nano ~/AFIV1/afi-core/full_audit.py
```

**Puntos a revisar:**
- Línea 17: Modelo IA usado (default: qwen2.5:14b)
- Línea 18: Días hacia atrás (default: 365)
- Línea 38-60: Prompt enviado al modelo
- Línea 81: Ruta donde guarda resultados (`/data/auditoria_*.json`)

---

### PASO 2: Levantar servicios necesarios
```bash
cd ~/AFIV1

# Levantar SOLO los servicios necesarios
docker compose up -d ollama-local chroma actual
```

**Esperar ~30 segundos** para que Ollama cargue el modelo en memoria.

---

### PASO 3: Verificar que Ollama está listo
```bash
# Probar que Ollama responde
docker compose exec ollama-local ollama list

# Debería mostrar: qwen2.5:14b (o el modelo configurado)
```

---

### PASO 4: Ejecutar auditoría CON logs en tiempo real
```bash
cd ~/AFIV1

# Opción A: Ver logs en tiempo real (recomendado)
docker compose run --rm \
  -e AUDIT_DAYS=365 \
  afi-core python /app/full_audit.py

# Opción B: Ejecutar en background y seguir logs después
docker compose run --rm -d \
  --name auditoria \
  -e AUDIT_DAYS=365 \
  afi-core python /app/full_audit.py
```

---

### PASO 5: Seguir los logs (si elegiste Opción B)
```bash
# Ver logs en tiempo real
docker logs -f auditoria

# Ver solo las últimas 50 líneas
docker logs --tail 50 auditoria

# Buscar palabras clave en los logs
docker logs auditoria | grep "procesados"
docker logs auditoria | grep "ERROR"
docker logs auditoria | grep "✅"
```

---

### PASO 6: Monitorear progreso
El script guarda progreso cada 10 correos. Puedes ver resultados parciales:

```bash
# Ver archivos de resultados
ls -lh ~/AFIV1/data/auditoria_*.json

# Ver resumen del último resultado
cat ~/AFIV1/data/auditoria_*.json | jq '{
  total: .total_correos,
  procesados: .procesados,
  cuentas: (.cuentas_bancarias | length),
  pasivos: (.pasivos | length),
  activos: (.activos | length),
  suscripciones: (.suscripciones | length)
}'
```

---

### PASO 7: Analizar resultados finales
```bash
# Ver estructura completa
cat ~/AFIV1/data/auditoria_*.json | jq '.'

# Ver solo cuentas encontradas
cat ~/AFIV1/data/auditoria_*.json | jq '.cuentas_bancarias'

# Ver solo pasivos
cat ~/AFIV1/data/auditoria_*.json | jq '.pasivos'

# Ver solo suscripciones
cat ~/AFIV1/data/auditoria_*.json | jq '.suscripciones'

# Contar transacciones por mes
cat ~/AFIV1/data/auditoria_*.json | jq '.transacciones | group_by(.fecha[0:7]) | map({mes: .[0].fecha[0:7], cantidad: length})'
```

---

### PASO 8: Apagar sistema cuando termine
```bash
cd ~/AFIV1
docker compose down
```

---

## ⚙️ CONFIGURACIÓN AVANZADA

### Cambiar período de análisis
```bash
# Últimos 30 días
docker compose run --rm -e AUDIT_DAYS=30 afi-core python /app/full_audit.py

# Últimos 90 días
docker compose run --rm -e AUDIT_DAYS=90 afi-core python /app/full_audit.py

# TODO el histórico (cuidado: puede tardar horas)
docker compose run --rm -e AUDIT_DAYS=3650 afi-core python /app/full_audit.py
```

### Usar modelo IA diferente
```bash
# Modelo más rápido (menos preciso)
docker compose run --rm \
  -e OLLAMA_MODEL="qwen2.5:1.5b" \
  afi-core python /app/full_audit.py

# Modelo más inteligente (más lento)
docker compose run --rm \
  -e OLLAMA_MODEL="qwen2.5:32b" \
  afi-core python /app/full_audit.py
```

---

## 🐛 SOLUCIÓN DE PROBLEMAS

### Error: "Sin credenciales de email"
```bash
# Verificar que .env tiene las credenciales
cat ~/AFIV1/.env | grep EMAIL
```

### Error: "Connection refused" (Ollama)
```bash
# Verificar que Ollama está corriendo
docker compose ps ollama-local

# Reiniciar Ollama
docker compose restart ollama-local
docker compose exec ollama-local ollama list
```

### Proceso muy lento
- El modelo Qwen 14B puede tardar 10-30 segundos por correo en CPU
- Para 1000 correos = ~3-8 horas
- Considera usar modelo más pequeño (qwen2.5:1.5b) para pruebas

### Ver uso de recursos
```bash
# CPU y RAM de contenedores
docker stats

# Espacio en disco
df -h ~/AFIV1/data/
```

---

## 📊 FORMATO DE RESULTADOS

El archivo `auditoria_*.json` tiene esta estructura:

```json
{
  "cuentas_bancarias": [
    "Banco Santander cuenta ****1234",
    "BBVA cuenta ****5678"
  ],
  "pasivos": [
    {
      "tipo": "tarjeta",
      "monto": 5000,
      "entidad": "Banco X"
    }
  ],
  "activos": [
    {
      "tipo": "inversión",
      "monto": 50000,
      "entidad": "Broker Y"
    }
  ],
  "suscripciones": [
    {
      "servicio": "Netflix",
      "monto_mensual": 15.99
    }
  ],
  "transacciones": [
    {
      "fecha": "2024-12-01",
      "monto": -500,
      "concepto": "Pago tarjeta",
      "from": "notificaciones@banco.com",
      "subject": "Pago procesado"
    }
  ],
  "total_correos": 1523,
  "procesados": 342
}
```

---

## ✅ CHECKLIST PARA MAÑANA

1. [ ] Revisar código: `cat ~/AFIV1/afi-core/full_audit.py`
2. [ ] Levantar servicios: `cd ~/AFIV1 && docker compose up -d ollama-local chroma actual`
3. [ ] Verificar Ollama: `docker compose exec ollama-local ollama list`
4. [ ] Ejecutar auditoría: `docker compose run --rm -e AUDIT_DAYS=365 afi-core python /app/full_audit.py`
5. [ ] Seguir logs en tiempo real
6. [ ] Analizar resultados: `cat ~/AFIV1/data/auditoria_*.json | jq '.'`
7. [ ] Apagar: `docker compose down`

---

## 🎓 COMANDOS ÚTILES

```bash
# Ver variables de entorno configuradas
docker compose config

# Entrar al contenedor para debug
docker compose run --rm -it afi-core bash

# Probar conexión IMAP manualmente
docker compose run --rm afi-core python -c "
from imap_tools import MailBox
import os
mb = MailBox('imap.gmail.com')
mb.login(os.getenv('EMAIL_USER'), os.getenv('EMAIL_PASS'))
print('✅ Conexión exitosa')
mb.logout()
"

# Limpiar espacio en disco
docker system prune -a
```

---

**Última actualización:** 2024-12-07
**Ubicación:** ~/AFIV1/INSTRUCCIONES_AUDITORIA.md
