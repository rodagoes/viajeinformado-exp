# Métricas REAL: ejecución periódica (PREPARADO, NO INSTALADO)

Este documento solo describe cómo programar `actualizar_metricas_reales`. No hay nada instalado en ningún servidor.

## Comando
```bash
python manage.py actualizar_metricas_reales            # aplica
python manage.py actualizar_metricas_reales --dry-run  # solo muestra el plan
```
Asegura el periodo "Producción AAAA", reconstruye los agregados REAL del año (idempotente) y no toca SIMULADO.
Con `METRICAS_REAL_HABILITADAS=False` avisa pero consolida igual los hechos REAL ya existentes (sin tracking
no hay hechos nuevos, así que es inofensivo). Se mantiene así: no hace falta salir antes.

## Frecuencia: cada hora
Coste: unas decenas de consultas agrupadas y ≤366 filas diarias; segundos con el volumen actual.
Pasar a cada 6 h solo si las sesiones anuales llegan a cientos de miles.

## Rutas (dato indicado por el responsable del proyecto; NO figuran en el repositorio, verificar en el servidor)
- WorkingDirectory: `/home/rodrigo/sget`
- venv: `/home/rodrigo/env3`
- settings de producción: `DJANGO_SETTINGS_MODULE=config.settings.production` (comprobar cómo lo fija el servicio actual).

## Opción recomendada: systemd timer
Ventajas frente a cron: logs en `journalctl`, un servicio `oneshot` no se solapa consigo mismo, `Persistent=true`
recupera ejecuciones perdidas si el servidor estuvo apagado.

`/etc/systemd/system/viajeinformado-metricas.service`
```ini
[Unit]
Description=Viaje Informado - actualizar métricas REAL

[Service]
Type=oneshot
User=rodrigo
WorkingDirectory=/home/rodrigo/sget
Environment=DJANGO_SETTINGS_MODULE=config.settings.production
ExecStart=/usr/bin/flock -n /tmp/viajeinformado-metricas.lock /home/rodrigo/env3/bin/python manage.py actualizar_metricas_reales
```
`/etc/systemd/system/viajeinformado-metricas.timer`
```ini
[Unit]
Description=Viaje Informado - métricas REAL cada hora

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```
Activación futura: `systemctl daemon-reload && systemctl enable --now viajeinformado-metricas.timer`.
Logs: `journalctl -u viajeinformado-metricas.service`. El `flock -n` evita que dos procesos creen a la vez el
periodo del año (no hay constraint única en la base de datos).

## Alternativa: cron
```cron
0 * * * * cd /home/rodrigo/sget && DJANGO_SETTINGS_MODULE=config.settings.production /usr/bin/flock -n /tmp/viajeinformado-metricas.lock /home/rodrigo/env3/bin/python manage.py actualizar_metricas_reales >> /home/rodrigo/logs/metricas.log 2>&1
```
(crear antes `/home/rodrigo/logs`; rotar con logrotate si crece.)

## .env de producción para la activación futura (NO aplicado)
```env
METRICAS_ADMIN_PRUEBAS_VISIBLE=False
METRICAS_REAL_HABILITADAS=True
METRICAS_HOME_ORIGEN=REAL
```
Si `METRICAS_REAL_HABILITADAS` falta, el tracking queda apagado. La Home sigue controlada desde
Admin > Configuración pública (`mostrar_metricas_home`).
