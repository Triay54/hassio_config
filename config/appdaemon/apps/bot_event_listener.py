# -*- coding: utf-8 -*-
"""
Automation task as a AppDaemon App for Home Assistant

Event listener for actions triggered from a Telegram Bot chat
or from iOS notification actions.

Harcoded custom logic for controlling HA with feedback from these actions.

"""
import datetime as dt
import json
import subprocess
from random import randrange
import re
from time import time

import appdaemon.plugins.hass.hassapi as hass
from fuzzywuzzy.process import extractOne

LOG_LEVEL = "DEBUG"
LOGGER = "event_log"

##################################################
# Colors, regexprs...
##################################################
XY_COLORS = {
    "red": [0.6736, 0.3221],
    "blue": [0.1684, 0.0416],
    "orange": [0.5825, 0.3901],
    "yellow": [0.4925, 0.4833],
    "green": [0.4084, 0.5168],
    "violet": [0.3425, 0.1383],
}
RG_COLOR = re.compile("(\\x1b\[\d{1,2}m)")
RG_TVS_DF = re.compile(
    "^(?P<ts>\d{4}-\d{2}-\d{2})\s+(?P<tvshow>.+?)\s+"
    "(?P<season>\d{1,2})\s+(?P<ep_number>\d{1,2})\s+"
    "(?P<title>.+?)\s+(?P<first_aired>\d{4}-\d{2}-\d{2})$"
)
rg_cron_common = (
    '(?P<command>.+[^\n])"\nnº execs this year: '
    "(?P<num_year>\d{1,4})\nNEXT: (?P<next_time>\d{2}:\d{2})\s"
    "(?P<next_date>\d{2}-\d{2}-\d{4})\s+?PREV: "
    "(?P<prev_time>\d{2}:\d{2})\s(?P<prev_date>\d{2}-\d{2}-\d{4})"
)
RG_CRON_JOB_REBOOT = re.compile('\*\* JOB: "@reboot ' + rg_cron_common)
RG_CRON_JOB = re.compile(
    '\*\* JOB: "(?P<p1>[^@]+?)\s(?P<p2>\S+)\s(?P<p3>\S+)'
    "\s(?P<p4>\S+)\s(?P<p5>\S+)\s" + rg_cron_common
)

##################################################
# Text templates (persistent notifications)
##################################################
DEFAULT_NOTIF_MASK = "Notificación recibida en {:%d/%m/%y %H:%M:%S} desde {}."
NOTIF_MASK_ALARM_ON = "ALARMA CONECTADA en {:%d/%m/%y %H:%M:%S}, desde '{}'."
NOTIF_MASK_LIGHTS_ON = (
    "Encendido de luces del salón a las " "{:%d/%m/%y %H:%M:%S}, desde '{}'."
)
NOTIF_MASK_LIGHTS_OFF = (
    "APAGADO DE LUCES a las {:%d/%m/%y %H:%M:%S}, " "desde '{}'."
)
NOTIF_MASK_ALARM_HOME = (
    "Vigilancia conectada en casa a las " "{:%d/%m/%y %H:%M:%S}, desde '{}'."
)
NOTIF_MASK_ALARM_SILENT = (
    "Se silencia la alarma a las " "{:%d/%m/%y %H:%M:%S}, desde '{}'."
)
NOTIF_MASK_ALARM_RESET = (
    "Se ignora el estado de alarma, reset a las "
    "{:%d/%m/%y %H:%M:%S}, desde '{}'."
)
NOTIF_MASK_ALARM_OFF = (
    "ALARMA DESCONECTADA en {:%d/%m/%y %H:%M:%S}, " "desde '{}'."
)
NOTIF_MASK_TOGGLE_AMB = (
    "Cambio en modo Ambilight: " "{:%d/%m/%y %H:%M:%S}, desde '{}'."
)
NOTIF_MASK_TOGGLE_AMB_CONF = (
    "Cambio en configuración de Ambilight (# de "
    "bombillas) {:%d/%m/%y %H:%M:%S}, desde '{}'."
)
NOTIF_MASK_ALARMCLOCK_OFF = (
    "{:%d/%m/%y %H:%M:%S}: Apagado de " "despertador (desde '{}')."
)
NOTIF_MASK_POSTPONE_ALARMCLOCK = (
    "{:%d/%m/%y %H:%M:%S}: Postponer " "despertador (desde '{}')."
)
NOTIF_MASK_INIT_DAY = (
    "{:%d/%m/%y %H:%M:%S}: A la ducha! Luces y " "Calefactor ON (desde '{}')."
)
NOTIF_MASK_LAST_VALIDATION = (
    "Validación a las {:%d/%m/%y %H:%M:%S}, " "desde '{}'."
)

##################################################
# Telegram commands & HASS wizard
##################################################
TELEGRAM_BOT_HELP = """*Comandos disponibles*:
/ambilightconfig - Cambio de la configuración de Ambilight.
/ambilighttoggle - Cambio del modo Ambilight (encender/apagar).
/armado - Activar la alarma.
/canceltimer - Cancela un temporizador.
/catappd - Muestra el LOG de AppDaemon.
/catappderr - Muestra el LOG de errores de AppDaemon.
/cathass - Muestra el LOG de Home Assistant.
/confirmar - Validar.
/desconectar - Desconectar la alarma.
/despertadoroff - Luces de dormitorio en 'Energy'.
/ducha - Luces de dormitorio en 'Energy' y encendido del calefactor.
/hasswiz - Inicia el asistente para interactuar con Home Assistant.
/hastatus - Devuelve información sobre el funcionamiento de Home Assistant.
/help - Muestra la descripción de los comandos disponibles.
/html - Render del texto pasado usando el parser HTML.
/ignorar - Resetear el estado de alarma.
/init - Ejecuta la misma acción que /start.
/llegada - Apagar la alarma y encender las luces.
/llegadatv - Apagar la alarma y encender las luces y la tele.
/lucesoff - Apagar las luces de casa.
/luceson - Luces del salón al 100%.
/osmc - Ejecuta un comando en el shell de la RPI3 del Salón.
/osmcmail - Muestra el syslog de la máquina OSMC.
/pitemps - Muestra la temperatura de la RPI.
/playkodi - Reproduce en Kodi la url pasada como argumento 
/plaympd - Reproduce en MPD como 'audio' la url pasada como argumento
/posponer - Posponer despertador unos minutos más.
/resetalarm - Ignorar el armado de alarma y resetearla.
/rpi - Ejecuta un comando en el shell de la RPI de Galería.
/rpi2 - Ejecuta un comando en el shell de la RPI2 del dormitorio.
/rpi2h - Ejecuta un comando en el shell de la RPI2 del Estudio.
/shell - Ejecuta un comando en el shell del host de HA (RPI3).
/silenciar - Silenciar la sirena de alarma.
/start - Muestra el mensaje de bienvenida y un teclado con comandos de ejemplo.
/status - Devuelve información actual de los sensores de la casa.
/template - Render del texto pasado como argumentos.
/test - Fuzzy recog de entidades por id o friendly name
/timeroff - Establece parada temporizada (+ ∆T + entity).
/timeron - Establece inicio temporizado (+ ∆T + entity).
/tvshowscron - Muestra la tabla CRON del TvShows Downloader.
/tvshowsdd - Descarga de capítulos: '/tvshowsdd game of thrones s02e10'.
/tvshowsinfo - Muestra información sobre la serie pasada como argumento.
/tvshowsnext - Muestra los capítulos de series de próxima emisión.
/vigilancia - Activar modo de vigilancia simple."""


TELEGRAM_SHELL_CMDS = [
    "/shell",
    "/osmc",
    "/osmcmail",
    "/rpi2",
    "/rpi2h",
    "/rpi",
    "/pitemps",
    "/cathass",
    "/catappd",
    "/catappderr",
    "/tvshowscron",
    "/tvshowsinfo",
    "/tvshowsdd",
    "/tvshowsnext",
]
TELEGRAM_HASS_CMDS = [
    "/getcams",
    "/status",
    "/hastatus",
    "/html",
    "/template",
    "/service_call",
    "/help",
    "/start",
    "/test",
    "/timeroff",
    "/timeron",
    "/canceltimer",
    "/playkodi",
    "/plaympd",
    "/init",
    "/hasswiz",
]
TELEGRAM_IOS_COMMANDS = {  # AWAY category
    "/armado": "ALARM_ARM_NOW",  # Activar alarma
    "/vigilancia": "ALARM_HOME",  # Activar vigilancia
    "/lucesoff": "LIGHTS_OFF",  # Apagar luces
    # INHOME category
    "/llegada": "WELCOME_HOME",  # Alarm OFF, lights ON
    "/llegadatv": "WELCOME_HOME_TV",  # AlarmOFF, lightsON
    "/ignorar": "IGNORE_HOME",  # Reset alarm state
    # ALARM category
    "/silenciar": "ALARM_SILENT",  # Silenciar sirena
    "/resetalarm": "ALARM_RESET",  # Ignorar armado, reset
    "/desconectar": "ALARM_CANCEL",  # Desconectar alarma
    # CONFIRM category
    "/confirmar": "CONFIRM_OK",  # Validar
    # KODIPLAY category
    "/luceson": "LIGHTS_ON",  # Lights ON!
    "/ambilighttoggle": "HYPERION_TOGGLE",
    "/ambilightconfig": "HYPERION_CHANGE",
    # Air purifier commands
    "/air_silent": "PURIFIER_SILENT",
    "/air_level": "PURIFIER_SET_LEVEL",
    "/air_off": "PURIFIER_OFF",
    # '/ambilighttoggle': 'HYPERION_TOGGLE',
    # '/ambilightconfig': 'HYPERION_CHANGE',
    # # ALARMCLOCK category
    "/ducha": "INIT_DAY",  # Luces Energy + Calefactor ON
    "/posponer": "POSTPONE_ALARMCLOCK",  # Postponer alarm
    "/despertadoroff": "ALARMCLOCK_OFF",  # Luces Energy
    "/input": "INPUTORDER",
}  # Tell me ('textInput')

COMMAND_PREFIX = "/"
COMMAND_WIZARD_OPTION = "op:"
TELEGRAM_INLINE_KEYBOARD = [
    [("ARMADO", "/armado"), ("Apaga las luces", "/lucesoff")],
    [("Llegada", "/llegada"), ("Llegada con TV", "/llegadatv")],
    [("Enciende luces", "/luceson"), ("Ambilight", "/ambilighttoggle")],
    [("Estado general", "/status"), ("HA status", "/hastatus")],
    [("Home assistant wizard!", "/hasswiz"), ("Ayuda", "/help")],
]
TELEGRAM_UNKNOWN = [
    "Cachis, no te he entendido eso de *{}*",
    "FORMATEAR TODO EN 5 segundos...\nEs broma, no voy a hacer ná de *{}*",
    "Prefiero no hacer eso de *{}*. No me van las cosas nuevas...",
    "Ein?, what is *{}*?",
    "Jopetas, no te pillo una, qué es eso de *{}*?",
    "No comprendo *{}*",
    "CMD *{}* NOT IMPLEMENTED!, Vamos, que ná de ná",
    "Sorry, I can't understand this: *{}*",
]

TELEGRAM_KEYBOARD = [
    "/armado, /lucesoff",
    "/llegada, /llegadatv",
    "/luceson, /ambilighttoggle",
    "/getcams",
    "/status, /hastatus, /help",
    "/hasswiz, /init",
]
HASSWIZ_MENU_ACTIONS = [
    ("Anterior ⬅︎", "op:back"),
    ("Inicio ▲", "op:reset"),
    ("Salir ✕", "op:exit"),
]
HASSWIZ_TYPES = ["switch", "light", "group", "sensor", "binary_sensor"]
HASSWIZ_STEPS = [
    {
        "question": "¿Qué *tipo de elemento* quieres controlar o consultar?",
        "options": [
            [("Interruptor", "op:switch"), ("Luz", "op:light")],
            [
                ("Grupo", "op:group"),
                ("Sensor", "op:sensor"),
                ("Indicador", "op:binary_sensor"),
            ],
            HASSWIZ_MENU_ACTIONS[2:],
        ],
    },
    {
        "question": "¿Qué acción quieres realizar "
        "con el tipo de elemento *{}*?",
        "options": [
            [("Encender", "op:turn_on"), ("Apagar", "op:turn_off")],
            [("Estado", "op:state"), ("Atributos", "op:attributes")],
            HASSWIZ_MENU_ACTIONS[1:],
        ],
    },
    {
        "question": "Selecciona un elemento para "
        "realizar acciones *{}* sobre él:",
        "options": None,
    },
]

INIT_MESSAGE = {
    "message": "_Say something to me_, *my master*",
    "inline_keyboard": TELEGRAM_INLINE_KEYBOARD,
    "disable_notification": True,
}
##################################################
# Remote SSH shell control
##################################################
PATH_SSH_KEY = "/home/homeassistant/.ssh/id_rsa"
SSH_PYTHON_ENVS_PREFIX = {
    "rpi3osmc": "/bin/bash /home/{0}/.bashrc; "
    "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/; "
    "/home/{0}/miniconda/envs/py35/bin/",
    "rpi2h": "/bin/bash /home/{0}/.bashrc;"
    "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/;"
    "/home/{0}/.pyenv/shims/",
    "rpi2": "/bin/bash /home/{0}/.bashrc;"
    "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/;"
    "source /home/{0}/PYTHON/py35/bin/activate;"
    "/home/{0}/PYTHON/py35/bin/",
    "rpi3w": "/bin/bash /home/{0}/.bashrc;"
    "export PYTHONPATH=$PYTHONPATH:/home/{0}/PYTHON/;"
    "source /home/{0}/PYTHON/py35/bin/activate;"
    "/home/{0}/PYTHON/py35/bin/",
}

##################################################
# Templates
##################################################
CMD_STATUS_TITLE = "*Estado de la casa*:"
CMD_STATUS_TEMPL_SALON = """*Salón*:
*LUCES* -> {{states.light.salon.state}} ({{relative_time(states.light.salon.last_changed)}})
- Tª: {% if states.sensor.salon_temperature %}{{(((states.sensor.salon_temperature.state|float) + (states.sensor.t_salon.state|float)) / 2)|round(1)}}{% else %}{{ states.sensor.t_salon.state }}{% endif %} ºC{% if states.sensor.salon_humidity %}
- HR: {{states.sensor.salon_humidity.state}} %{%endif %}
- Mov: {{states.binary_sensor.pir_salon.state}} ({{relative_time(states.binary_sensor.pir_salon.last_changed)}})
- VMov: {{states.binary_sensor.motioncam_salon.state}} ({{relative_time(states.binary_sensor.motioncam_salon.last_changed)}})
{{states.switch.camara.attributes.friendly_name}}: {{states.switch.camara.state}} ({{relative_time(states.switch.camara.last_changed)}})
Ambilight: {{states.switch.toggle_kodi_ambilight.state}} ({{relative_time(states.switch.toggle_kodi_ambilight.last_changed)}})
KODI: {{states.media_player.kodi.state}} ({{relative_time(states.media_player.kodi.last_changed)}})

*{{states.light.bola_grande.attributes.friendly_name}}* -> {{states.light.bola_grande.state}} ({{relative_time(states.light.bola_grande.last_changed)}})
*{{states.light.bola_pequena.attributes.friendly_name}}* -> {{states.light.bola_pequena.state}} ({{relative_time(states.light.bola_pequena.last_changed)}})
*{{states.light.cuenco.attributes.friendly_name}}* -> {{states.light.cuenco.state}} ({{relative_time(states.light.cuenco.last_changed)}})
*{{states.light.lamparita.attributes.friendly_name}}* -> {{states.light.lamparita.state}} ({{relative_time(states.light.lamparita.last_changed)}})
*{{states.light.pie_tv.attributes.friendly_name}}* -> {{states.light.pie_tv.state}} ({{relative_time(states.light.pie_tv.last_changed)}})
*{{states.light.pie_sofa.attributes.friendly_name}}* -> {{states.light.pie_sofa.state}} ({{relative_time(states.light.pie_sofa.last_changed)}})

*{{states.switch.switch_master_alarm.attributes.friendly_name}}: {{states.switch.switch_master_alarm.state}} ({{relative_time(states.switch.switch_master_alarm.last_changed)}})*"""
CMD_STATUS_TEMPL_DORM = """*Dormitorio*:
*LUCES* -> {{states.light.dormitorio.state}} ({{relative_time(states.light.dormitorio.last_changed)}})
- Tª: {{states.sensor.temperatura_dormitorio_rpi2mpd.state}} ºC
- HR: {{states.sensor.humedad_dormitorio_rpi2mpd.state}} %
- P: {{states.sensor.presion_dormitorio_rpi2mpd.state}} mbar
- Mov: {{states.binary_sensor.pir_dormitorio_rpi2mpd.state}} ({{relative_time(states.binary_sensor.pir_dormitorio_rpi2mpd.last_changed)}})
Altavoz: {{states.switch.altavoz.state}} ({{relative_time(states.switch.altavoz.last_changed)}})
Mopidy: {{states.media_player.dormitorio_mopidy.state}} ({{relative_time(states.media_player.dormitorio_mopidy.last_changed)}})
Despertador ({{states.switch.alarm_clock_status.state}}) a las {{states.sensor.alarm_clock_time.state}}.
{{states.switch.calefactor.attributes.friendly_name}}: {{states.switch.calefactor.state}} ({{relative_time(states.switch.calefactor.last_changed)}})

*Luz* -> {{states.light.hue_habitacion.state}} ({{relative_time(states.light.hue_habitacion.last_changed)}})
*Lamparita* -> {{states.light.aura_habitacion.state}} ({{relative_time(states.light.aura_habitacion.last_changed)}})"""
CMD_STATUS_TEMPL_COCINA = """*Cocina*:
- Tª: {{states.sensor.esp1_temperature.state}} ºC
- HR: {{states.sensor.esp1_humidity.state}} %
- Luz: {{states.sensor.esp1_light.state}} %
- Mov: {{states.binary_sensor.esp1_pir.state}} ({{relative_time(states.binary_sensor.esp1_pir.last_changed)}})

ESP Leds: {{states.switch.use_esp1_leds.state}}
ESP Binary sensor: {{states.switch.use_esp1_pir.state}}
ESP Online: {{states.binary_sensor.cocina_online.state}} ({{relative_time(states.binary_sensor.cocina_online.last_changed)}})

*{{states.switch.cocina.attributes.friendly_name}}* -> {{states.switch.cocina.state}} ({{relative_time(states.switch.cocina.last_changed)}})"""
CMD_STATUS_TEMPL_GALERIA = """*Galería*:
- Tª: {{states.sensor.galeria_dht22_temperature.state}} ºC
- HR: {{states.sensor.galeria_dht22_humidity.state}} %"""
CMD_STATUS_TEMPL_HEATER = """*Caldera*:
{{states.switch.caldera.attributes.friendly_name}}: {{states.switch.caldera.state}} ({{relative_time(states.switch.caldera.last_changed)}})
- Calefacción: {{states.binary_sensor.heating.state}} ({{relative_time(states.binary_sensor.heating.last_changed)}}), status: {{states.sensor.calefaccion.state}} ({{relative_time(states.sensor.calefaccion.last_changed)}})
- ACS: {{states.sensor.galeria_acs.state}} ºC
- Impulsión: {{states.sensor.galeria_impulsion_calefaccion.state}} ºC
- Retorno: {{states.sensor.galeria_retorno_calefaccion.state}} ºC"""
CMD_STATUS_TEMPL_ESP = """*ESP8266*:
- Tª: {{states.sensor.esp2_temperature.state}} ºC
- HR: {{states.sensor.esp2_humidity.state}} %
- P: {{states.sensor.esp2_pressure.state}} mbar
- Luz: {{states.sensor.esp2_light.state}} %
- Mov: {{states.binary_sensor.esp2_pir.state}} ({{relative_time(states.binary_sensor.esp2_pir.last_changed)}})
- Vibr: {{states.binary_sensor.esp2_vibro.state}} ({{relative_time(states.binary_sensor.esp2_vibro.last_changed)}})

ESP Leds: {{states.switch.use_esp1_leds.state}}
ESP Binary sensor: {{states.switch.use_esp1_pir.state}}
ESP Online: {{states.binary_sensor.esp2_online.state}} ({{relative_time(states.binary_sensor.esp2_online.last_changed)}})"""
CMD_TEMPL_HASS_STATUS = """*HASS Status*:
*¿Problemas? -> {{states.binary_sensor.services_notok.state}}* ({{relative_time(states.binary_sensor.services_notok.last_changed)}})
- IP: {{states.sensor.ip_externa.state}}
- Internet: DL {{states.sensor.speedtest_download.state|int}} Mbps / UL {{states.sensor.speedtest_upload.state|int}} Mbps / ping {{states.sensor.speedtest_ping.state|int}}ms
Funcionando desde {{states.sensor.last_boot.state}} (HASS {{relative_time(states.sensor.last_boot.last_changed)}}). CPU {{states.sensor.processor_use.state}} %, Tª {{states.sensor.hass_cpu_temperature.state}} %, RAM FREE {{states.sensor.memory_free.state}} MB, SD al {{states.sensor.disk_use_percent.state}} %"""

MAIN_PLAYER = "media_player.kodi"
BEDROOM_PLAYER = "media_player.dormitorio_mopidy"


def _clean(telegram_text):
    """Remove markdown characters to prevent
    Telegram parser to fail ('_' & '*' chars)."""
    return telegram_text.replace("_", "\_").replace("*", "")


# noinspection PyClassHasNoInit
class EventListener(hass.Hass):
    """Event listener for ios actions and Telegram bot events."""

    # _config = None
    _base_url = None

    _lights_notif = None
    _lights_notif_state = None
    _lights_notif_st_attr = None
    _notifier = None

    _bot_notifier = "telegram_bot"
    _bot_name = None
    _bot_wizstack = None
    _bot_chatids = None
    _bot_users = None

    # Alarm state
    _alarm_state = False

    # HASS entities:
    _hass_entities = None
    _hass_entities_plain = None

    # Scheduled tasks
    _scheduled = {}

    def initialize(self):
        """AppDaemon required method for app init."""
        self._bot_name = "@" + self.args.get("bot_name")
        self._base_url = self.args.get("base_url")
        self._notifier = self.config.get("notifier").replace(".", "/")
        _chatids = [int(x) for x in self.args.get("bot_chatids").split(",")]
        _nicknames = self.args.get("bot_nicknames").split(",")
        self._bot_chatids = _chatids
        self._bot_users = {c: u for c, u in zip(self._bot_chatids, _nicknames)}
        self._lights_notif = self.args.get("lights_notif", "light.cuenco")
        self._bot_wizstack = {user: [] for user in self._bot_users.keys()}

        # iOS app notification actions
        [
            self.listen_event(self.receive_ios_event, ev)
            for ev in [
                "ios.notification_action_fired",
                "ios_iphone.notification_action_fired",
            ]
        ]

        # Telegram Bot
        [
            self.listen_event(self.receive_telegram_event, ev)
            for ev in [
                "telegram_command",
                "telegram_text",
                "telegram_callback",
            ]
        ]

        # Flash light event
        self.listen_event(self.receive_flash_light_event, "flash_light")

        # Alarm mode controller
        if self.get_state("switch.switch_master_alarm") and self.get_state(
            "input_select.alarm_mode"
        ):
            self.listen_state(
                self.alarm_mode_controller, entity="input_select.alarm_mode"
            )
            self.listen_state(
                self.alarm_mode_controller_master_switch,
                entity="switch.switch_master_alarm",
            )
            self._alarm_state = (
                self.get_state("switch.switch_master_alarm") == "on"
            )
        else:
            self._alarm_state = False

        # Entities & friendly names:
        self._hass_entities = {
            ent_type: {
                k.split(".")[1]: v["attributes"]["friendly_name"]
                for k, v in self.get_state(ent_type).items()
                if v is not None
                and "attributes" in v
                and "friendly_name" in v["attributes"]
            }
            for ent_type in HASSWIZ_TYPES
        }
        self._hass_entities_plain = {
            "{}.{}".format(domain, ent): fn
            for domain, entities in self._hass_entities.items()
            for ent, fn in entities.items()
        }

    def fuzzy_get_entity_and_fn(self, entity_id_name):
        """Fuzzy get of HA entities"""
        friendly_name = entity_id = None
        if "." in entity_id_name:
            if self.entity_exists(entity_id_name):
                friendly_name = self.friendly_name(entity_id_name)
                entity_id = entity_id_name
            else:
                # Fuzzy lookup
                choices = self._hass_entities_plain.keys()
                found = extractOne(entity_id_name, choices, score_cutoff=70)
                if found is not None:
                    entity_id = found[0]
                    friendly_name = self.friendly_name(entity_id)
                else:
                    self.log(
                        'Entity not recognized: "{}" -> {}'.format(
                            entity_id_name, choices
                        ),
                        log=LOGGER,
                    )
        else:
            # Fuzzy lookup in friendly names
            choices = self._hass_entities_plain.values()
            found = extractOne(entity_id_name, choices, score_cutoff=70)
            if found is not None:
                friendly_name = found[0]
                entity_id = list(
                    sorted(
                        filter(
                            lambda x: self._hass_entities_plain[x]
                            == friendly_name,
                            self._hass_entities_plain,
                        ),
                        reverse=True,
                    )
                )
                self.log(
                    "fuzzy: {} --> {}".format(found, entity_id),
                    level="DEBUG",
                    log=LOGGER,
                )
                entity_id = entity_id[0]
            else:
                # Fuzzy lookup in entity names
                choices = [x.split(".") for x in self._hass_entities_plain]
                simple_names = list(zip(*choices))[1]
                simple_found = extractOne(entity_id_name, simple_names)[0]
                entity_id = "{}.{}".format(
                    list(zip(*choices))[0][simple_names.index(simple_found)],
                    simple_found,
                )
                friendly_name = self.friendly_name(entity_id)
        self.log(
            'Entity fuzzy recog: "{}" -> `{}`, "{}"'.format(
                entity_id_name, entity_id, friendly_name
            ),
            log=LOGGER,
        )
        return entity_id, friendly_name

    def _shell_command_output(self, cmd, timeout=10, **kwargs):
        """Exec a shell command in a subprocess and capture output.

        Returns ok, render, filtered_stdout
        """
        popenargs = cmd.split() if " " in cmd else cmd
        try:
            out = subprocess.check_output(
                popenargs, timeout=timeout, stderr=subprocess.STDOUT, **kwargs
            ).decode()
            return True, False, RG_COLOR.sub("", out)
        except subprocess.CalledProcessError as e:
            self.log(
                "CalledProcessError with {} -> {}, [{}]".format(
                    cmd, e, e.__class__
                ),
                log=LOGGER,
            )
            return False, False, e.output.decode()
        except Exception as e:
            clean_e = str(e).replace("[", "(").replace("]", ")")
            msg = "CHECK_OUTPUT ERROR: {} {}".format(clean_e, e.__class__)
            return False, False, msg

    def _exec_bot_shell_command(self, command, args, timeout=20, **kwargs):
        self.log(
            'in shell_command_output with "{}", "{}"'.format(command, args),
            level=LOG_LEVEL,
            log=LOGGER,
        )
        if command == "/pitemps":
            cmd = "python3 /home/pi/pitemps.py"
            return self._shell_command_output(cmd, timeout=timeout, **kwargs)
        else:  # shell cmd
            return self._shell_command_output(
                " ".join(args), timeout=timeout, **kwargs
            )

    def _run_scheduled(self, kwargs):
        mode = kwargs["mode"]
        context = kwargs["context"]
        entity_id = kwargs["entity_id"]
        fn = kwargs["fn"]
        self.call_service("homeassistant/turn_" + mode, entity_id=entity_id)
        self._scheduled.pop((mode, entity_id))
        action = "Encendido" if mode == "on" else "Apagado"
        run_delay = context["run_delay"]
        self.log(
            "Scheduled RUN: TimerOut turn_{} {} after {}s".format(
                mode, entity_id, run_delay
            ),
            log=LOGGER,
        )
        cmd = "/service_call homeassistant/turn_"
        keyboard = [
            "Encender {}:{}on {}".format(fn, cmd, entity_id),
            "Apagar {}:{}off {}".format(fn, cmd, entity_id),
        ]
        msg = dict(
            title="*Ejecución temporizada*",
            message="{} de {} después de {} sec".format(
                action, self.friendly_name(entity_id), run_delay
            ),
            target=context["target"],
            disable_notification=False,
            inline_keyboard=keyboard,
        )
        self.call_service(self._bot_notifier + "/send_message", **msg)

    def _cancel_scheduled(self, mode, entity_id):
        handler = self._scheduled.pop((mode, entity_id))
        self.cancel_timer(handler)
        self.log(
            "Cancelled Timer {}. Scheduled calls: {}".format(
                handler, self._scheduled
            ),
            log=LOGGER,
        )

    def _bot_hass_cmd(self, command, cmd_args, user_id):
        serv = self._bot_notifier + "/send_message"
        prefix = "WTF CMD {}".format(command)
        msg = {
            "message": "ERROR {} - {}".format(command, cmd_args),
            "target": user_id,
        }
        if command == "/hasswiz":  # HASS wizard:
            msg = dict(
                title="*HASS Wizard*",
                message=HASSWIZ_STEPS[0]["question"],
                target=user_id,
                inline_keyboard=HASSWIZ_STEPS[0]["options"],
            )
            prefix = "START HASS WIZARD"
        elif command == "/help":
            # Welcome message & keyboards:
            prefix = "SHOW BOT HELP"
            msg = dict(
                target=user_id,
                message=TELEGRAM_BOT_HELP,
                inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                disable_notification=False,
            )
        elif (command == "/init") or (command == "/start"):
            # Welcome message & keyboards:
            prefix = "BOT START"
            msg = dict(target=user_id, **INIT_MESSAGE)
        elif command == "/service_call":
            # /service_call media_player/turn_off media_player.kodi
            prefix = "HASS SERVICE CALL"
            msg = dict(
                target=user_id,
                message="*Bad service call*: %s" % cmd_args,
                inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                disable_notification=False,
            )
            if cmd_args:
                serv = cmd_args[0].replace(".", "/")
                if len(cmd_args) == 2:
                    if cmd_args[1][0] == "{":
                        msg = json.loads(" ".join(cmd_args[1:]))
                    else:
                        msg = {"entity_id": cmd_args[1].lstrip("entity_id=")}
                elif len(cmd_args) > 2:
                    msg["entity_id"] = cmd_args[1]
                    if serv == "climate/set_operation_mode":
                        msg["operation_mode"] = cmd_args[2]
                        # WTF:
                        # when creating InlineKeyboardButton's, this call fails with: 'Button_data_invalid'
                        # "inline_keyboard": ["Deshacer:/service_call climate.set_operation_mode climate.termostato_ac off"],
                        # but these are ok:
                        # "inline_keyboard": ["Deshacer:/service_call climate.set_operation_mode termostato_ac off"],
                        # "inline_keyboard": ["Deshacer:/service_call set_operation_mode climate.termostato_ac off"],
                        # like there is a problem when the number of '.' is > 1 ¿¿¿???
                        if "climate." not in msg["entity_id"]:
                            msg["entity_id"] = "climate." + msg["entity_id"]
                    elif cmd_args[2][0] == "{":
                        msg = json.loads(" ".join(cmd_args[2:]))
                    else:
                        self.error(
                            "Service call bad args (no JSON): {}".format(
                                cmd_args
                            )
                        )
            self.log(
                "Generic Service call: {}({})".format(serv, msg), log=LOGGER
            )
        elif command == "/playkodi" or command == "/plaympd":
            use_kodi = command == "/playkodi"
            prefix = "PLAY MEDIA ({})".format(command)
            if cmd_args:
                media_type = None
                if len(cmd_args) == 2:
                    media_type = cmd_args[1].upper()
                self.play_url_in_media_player(
                    user_id,
                    cmd_args[0],
                    use_kodi=use_kodi,
                    media_type=media_type,
                )
                serv, msg = "", {}
        elif command == "/timeroff" or command == "/timeron":
            # /timeroff 9:30 media_player.kodi
            # /timeron 1h media_player.kodi
            now = dt.datetime.now()
            msg = dict(
                target=user_id,
                message="*Bad scheduled service call*: %s" % cmd_args,
                inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                disable_notification=True,
            )
            mode = command.lstrip("/timer_")
            prefix = "HASS TIMER " + mode.upper()
            if cmd_args:
                runtime = cmd_args[0]
                entity, fn = self.fuzzy_get_entity_and_fn(
                    " ".join(cmd_args[1:])
                )
                if ":" in runtime:
                    future = dt.datetime.combine(
                        now.date(),
                        dt.time(*[int(x) for x in runtime.split(":")]),
                    )
                    run_delay = (future - now).total_seconds()
                    if run_delay < 0:
                        run_delay += 3600 * 24
                elif "h" in runtime:
                    run_delay = 3600 * int(runtime[: runtime.index("h")])
                elif "m" in runtime:
                    run_delay = 60 * int(runtime[: runtime.index("m")])
                elif "s" in runtime:
                    run_delay = int(runtime[: runtime.index("s")])
                else:
                    run_delay = int(runtime)

                if (mode, entity) in self._scheduled:
                    self._cancel_scheduled(mode, entity)
                handler = self.run_in(
                    self._run_scheduled,
                    run_delay,
                    mode=mode,
                    entity_id=entity,
                    fn=fn,
                    context={"target": user_id, "run_delay": run_delay},
                )
                self._scheduled[(mode, entity)] = handler
                str_time = (
                    (now + dt.timedelta(seconds=run_delay))
                    .replace(microsecond=0)
                    .time()
                    .isoformat()
                )
                cbtn = "Cancelar temporizador ({}):/cancel_timer {}"
                msg["inline_keyboard"] = [cbtn.format(str_time, handler)]
                msg["title"] = "Temporizador *{}* {}".format(
                    mode, self.friendly_name(entity)
                )
                msg["message"] = "*Timer {}*: {} -> delay: {} sec".format(
                    mode.upper(), cmd_args, run_delay
                )
                self.log(
                    "Timer {} entity {} in {}s ({}) -> {}".format(
                        mode, entity, run_delay, runtime, handler
                    ),
                    log=LOGGER,
                )
            else:
                self.log(
                    "Timer {} bad call: {}".format(mode.upper(), cmd_args),
                    log=LOGGER,
                )
        elif command == "/canceltimer":
            # /cancel_timer handler_id
            prefix = "HASS CANCEL TIMER"
            msg = dict(
                target=user_id,
                message="*Bad cancel_timer call*: %s" % cmd_args,
                disable_notification=True,
            )
            if cmd_args:
                if len(cmd_args) > 1:
                    mode = cmd_args[0].lower()
                    entity_id, fn = self.fuzzy_get_entity_and_fn(
                        " ".join(cmd_args[1:])
                    )
                    if (mode, entity_id) in self._scheduled:
                        self._cancel_scheduled(mode, entity_id)
                        msg["message"] = "Timer {} for {} cancelled".format(
                            mode, entity_id
                        )
                    else:
                        self.log(
                            "Can't cancel timer {} {}: {}".format(
                                mode, entity_id, self._scheduled
                            ),
                            log=LOGGER,
                        )
                else:
                    handler = cmd_args[0]
                    keys = list(
                        filter(
                            lambda x: str(self._scheduled[x]) == handler,
                            self._scheduled,
                        )
                    )
                    if keys:
                        self._cancel_scheduled(*keys[0])
                        msg["message"] = "Timer {} for {} cancelled".format(
                            *keys[0]
                        )
                    else:
                        self.log(
                            "Can't cancel timer with handler_id {}, {}".format(
                                handler, self._scheduled
                            ),
                            log=LOGGER,
                        )
            else:
                self.log("Cancel Timer bad call (no args!)", log=LOGGER)
        elif command == "/status":
            # multiple messaging:
            msg = dict(
                title=CMD_STATUS_TITLE,
                message=CMD_STATUS_TEMPL_SALON,
                target=user_id,
                keyboard=TELEGRAM_KEYBOARD,
                disable_notification=True,
            )
            self.call_service(serv, **msg)
            msg.pop("title")
            msg.pop("keyboard")
            msg["message"] = CMD_STATUS_TEMPL_DORM
            self.call_service(serv, **msg)
            msg["message"] = CMD_STATUS_TEMPL_COCINA
            self.call_service(serv, **msg)
            msg["message"] = CMD_STATUS_TEMPL_GALERIA
            self.call_service(serv, **msg)
            msg["message"] = CMD_STATUS_TEMPL_HEATER
            self.call_service(serv, **msg)
            msg["message"] = CMD_STATUS_TEMPL_ESP
            msg.update(
                dict(
                    inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                    disable_notification=False,
                )
            )
            prefix = "SHOW HASS STATUS"
        elif command == "/hastatus":
            msg = dict(
                message=CMD_TEMPL_HASS_STATUS,
                target=user_id,
                inline_keyboard=TELEGRAM_INLINE_KEYBOARD,
                disable_notification=False,
            )
            prefix = "SHOW HASS PROCESS STATUS"
        elif command == "/html":
            msg = dict(
                parse_mode="html",
                keyboard=TELEGRAM_KEYBOARD,
                message=" ".join(cmd_args),
                target=user_id,
            )
            prefix = "HTML RENDER"
        elif command == "/template":
            msg = dict(
                message=" ".join(cmd_args),
                target=user_id,
                keyboard=TELEGRAM_KEYBOARD,
            )
            prefix = "TEMPLATE RENDER"
        elif command == "/test":
            args = " ".join(cmd_args)
            self.log('TEST FUZZY ENTITY: "{}"'.format(args), log=LOGGER)
            entity, fn = self.fuzzy_get_entity_and_fn(args)
            message = 'TEST FUZZY "{}" -> {}, {}'.format(args, entity, fn)
            self.log(message, log=LOGGER)
            msg = dict(
                message=_clean(message),
                target=user_id,
                disable_notification=True,
            )
            prefix = "TEST METHOD"
        return serv, prefix, msg

    # noinspection PyUnusedLocal
    def alarm_mode_controller(self, entity, attribute, old, new, kwargs):
        """Cambia el master switch cuando se utiliza el input_select"""
        self.log("ALARM_MODE_CONTROLLER {} -> {}".format(old, new), log=LOGGER)
        if new == "Desconectada":
            self._alarm_state = False
            self.turn_off("switch.switch_master_alarm")
        elif new == "Fuera de casa":  # and (old == 'Desconectada'):
            self._alarm_state = True
            self.turn_on("switch.switch_master_alarm")
        # TODO modo vigilancia "en casa" / "fuera", "vacaciones"

    # noinspection PyUnusedLocal
    def alarm_mode_controller_master_switch(
        self, entity, attribute, old, new, kwargs
    ):
        """Cambia el input_select cuando se utiliza el master switch"""
        self.log(
            "ALARM_MODE_CONTROLLER_MASTER_SWITCH {} -> {}".format(old, new),
            log=LOGGER,
        )
        selected_mode = self.get_state("input_select.alarm_mode")
        if new == "on":
            self._alarm_state = True
            if selected_mode == "Desconectada":
                self.select_option(
                    "input_select.alarm_mode", option="Fuera de casa"
                )
        elif new == "off":
            self._alarm_state = False
            if selected_mode != "Desconectada":
                self.select_option(
                    "input_select.alarm_mode", option="Desconectada"
                )

    def light_flash(
        self,
        xy_color,
        persistence: float = 5.0,
        n_flashes: int = 3,
        transition: float = 1.0,
    ):
        """Flash hue lights as visual notification."""

        def _turn_on(*args_runin):
            params = args_runin[0]
            self.call_service(
                "light/turn_on",
                entity_id=params["entity_id"],
                xy_color=params["xy_color"],
                transition=params["transition"],
                brightness=params["brightness"],
            )

        def _turn_off(*args_runin):
            params = args_runin[0]
            self.call_service(
                "light/turn_off",
                entity_id=params["entity_id"],
                transition=params["transition"],
            )

        # noinspection PyUnusedLocal
        def _restore_state(*args):
            for light, st, attrs in zip(
                self._lights_notif.split(","),
                self._lights_notif_state,
                self._lights_notif_st_attr,
            ):
                if st == "on":
                    try:
                        self.call_service(
                            "light/turn_on",
                            entity_id=light,
                            transition=1,
                            xy_color=attrs["attributes"]["xy_color"],
                            brightness=attrs["attributes"]["brightness"],
                        )
                    except KeyError as exc:
                        self.log(
                            "BAD LIGHT[{}] RESTORE ATTRS: {}".format(
                                light, attrs
                            ),
                            log=LOGGER,
                        )
                        self.call_service(
                            "light/turn_on",
                            entity_id=light,
                            transition=1,
                            **attrs["attributes"],
                        )
                else:
                    self.call_service(
                        "light/turn_off", entity_id=light, transition=1
                    )

        # Get prev state:
        self._lights_notif_state = [
            self.get_state(l) for l in self._lights_notif.split(",")
        ]
        self._lights_notif_st_attr = [
            self.get_state(l, attribute="all")
            for l in self._lights_notif.split(",")
        ]
        self.log(
            'Flashing "{}" {} times, persistence={}s, trans={}s.'.format(
                self._lights_notif, n_flashes, persistence, transition
            ),
            log=LOGGER,
        )

        # Loop ON-OFF
        self.call_service(
            "light/turn_off", entity_id=self._lights_notif, transition=0
        )
        self.call_service(
            "light/turn_on",
            entity_id=self._lights_notif,
            transition=transition,
            xy_color=xy_color,
            brightness=254,
        )
        run_in = int(persistence + transition)
        for i in range(1, n_flashes):
            self.run_in(
                _turn_off,
                run_in,
                entity_id=self._lights_notif,
                transition=transition,
            )
            run_in += int(persistence + transition)
            self.run_in(
                _turn_on,
                run_in,
                entity_id=self._lights_notif,
                xy_color=xy_color,
                transition=transition,
                brightness=254,
            )
            run_in += int(persistence + transition)

        # Restore state
        self.run_in(
            _restore_state,
            run_in + persistence - 2,
            entity_id=self._lights_notif,
            transition=2,
        )

    def receive_flash_light_event(self, event_id, payload_event, *args):
        """Event listener for flash light events."""
        color = payload_event.get("color", "red")
        flashes = payload_event.get("flashes", 1)
        persistence = float(payload_event.get("persistence", 1))
        transition = float(payload_event.get("transition", 1))
        lights_use = payload_event.get("lights", None)
        if lights_use is not None:
            self._lights_notif = lights_use
        self.log(
            "flash_light_event received: {} - #{}/{}s".format(
                color, flashes, persistence
            ),
            log=LOGGER,
            level="DEBUG",
        )
        self.light_flash(
            XY_COLORS[color],
            persistence=persistence,
            n_flashes=flashes,
            transition=transition,
        )

    def receive_ios_event(self, event_id, payload_event, *args):
        """Event listener."""
        if "notification_action_fired" in event_id:
            action_name = payload_event["actionName"]
            if (
                action_name
                == "com.apple.UNNotificationDefaultActionIdentifier"
            ) or (
                action_name
                == "com.apple.UNNotificationDismissActionIdentifier"
            ):
                # iOS Notification discard
                self.log(
                    "NOTIFICATION Discard: {} - Args={}, more={}".format(
                        event_id, payload_event, args
                    ),
                    log=LOGGER,
                )
            else:
                dev = payload_event["sourceDeviceName"]
                self.log(
                    'RESPONSE_TO_ACTION "{}" from dev="{}", otherArgs ={}'.format(
                        action_name, dev, payload_event
                    ),
                    log=LOGGER,
                )
                self.response_to_action(action_name, dev, *args)
        else:
            self.log(
                'NOTIFICATION WTF: "{}", payload={}, otherArgs={}'.format(
                    event_id, payload_event, args
                ),
                log=LOGGER,
            )

    def play_url_in_media_player(
        self, target, media_url, use_kodi=True, media_type=None
    ):
        """Use the media_extractor service to play video or audio."""
        if media_type is None:
            media_type = "VIDEO" if use_kodi else "AUDIO"
        entity_id = MAIN_PLAYER if use_kodi else BEDROOM_PLAYER

        # Play media
        service_data = {
            "entity_id": entity_id,
            "media_content_id": media_url,
            "media_content_type": media_type,
        }
        self.call_service("media_extractor/play_media", **service_data)

        msg = "Playing ```{}```in {}".format(
            media_url, self.friendly_name(entity_id)
        )
        inline_keyboard = [
            ", ".join(
                [
                    "OFF:/service_call media_player.turn_off " + entity_id,
                    "ON:/service_call media_player.turn_on " + entity_id,
                    "‖:/service_call media_player.media_play_pause "
                    + entity_id,
                    "◼︎:/service_call media_player.media_stop " + entity_id,
                ]
            )
        ]
        self.call_service(
            self._bot_notifier + "/send_message",
            target=target,
            disable_notification=False,
            inline_keyboard=inline_keyboard,
            message=msg,
        )

    def process_telegram_command(
        self, command, cmd_args, user_id, callback_id=None
    ):
        """Handle telegram_command's received."""
        tic = time()
        if callback_id is not None:
            msg = dict(callback_query_id=callback_id, show_alert=False)
            service = self._bot_notifier + "/answer_callback_query"
        else:
            msg = dict(target=user_id)
            service = self._bot_notifier + "/send_message"
        if command in TELEGRAM_IOS_COMMANDS:  # Same as iOS notification:
            msg["message"] = "Exec: *{}* action".format(command)
            if callback_id is not None:
                msg["message"] = msg["message"].replace("*", "")
            self.call_service(service, **msg)
            self.log("TELEGRAM_COMMAND exec: {}".format(command), log=LOGGER)
            self.response_to_action(
                TELEGRAM_IOS_COMMANDS[command],
                self._bot_users[user_id],
                telegram_target=(user_id, callback_id),
            )
        elif command in TELEGRAM_SHELL_CMDS:
            msg["message"] = "_Running shell cmd_: {}".format(command)
            if callback_id is not None:
                msg["message"] = msg["message"].replace("_", "")
            self.call_service(service, **msg)
            ok, render, out = self._exec_bot_shell_command(command, cmd_args)
            if len(out) > 4000:
                out = out[-4000:]
            self.log(
                "SHELL CMD TOOK {:.3f}s -> {} {}".format(
                    time() - tic, command, cmd_args
                ),
                log=LOGGER,
            )
            title = "*SHELL CMD OK*\n" if ok else "*SHELL CMD ERROR!*:\n"
            if ok and render:
                message = "\n{}\n".format(out)
            else:
                message = "```\n{}\n```".format(out.replace("```", ""))
            self.call_service(
                self._bot_notifier + "/send_message",
                title=title,
                target=user_id,
                message=message,
            )
        elif command in TELEGRAM_HASS_CMDS:
            if callback_id is not None:
                msg["message"] = "Running: {}".format(_clean(command))
                self.call_service(service, **msg)
            serv, prefix, msg = self._bot_hass_cmd(command, cmd_args, user_id)
            self.log(
                "{} TOOK {:.3f}s".format(prefix, time() - tic), log=LOGGER
            )
            if serv and msg:
                self.call_service(serv, **msg)
        else:
            rand_msg_mask = TELEGRAM_UNKNOWN[randrange(len(TELEGRAM_UNKNOWN))]
            p_cmd = "{}({})".format(command, cmd_args)
            message = rand_msg_mask.format("{}({})".format(command, cmd_args))
            self.log(
                "NOT IMPLEMENTED: " + rand_msg_mask.format(p_cmd), log=LOGGER
            )
            self.call_service(
                self._bot_notifier + "/send_message",
                target=user_id,
                keyboard=TELEGRAM_KEYBOARD,
                message=message,
            )

    def process_telegram_wizard(
        self, msg_origin, data_callback, user_id, callback_id
    ):
        """Run wizard steps."""
        # Wizard evolution:
        option = data_callback[len(COMMAND_WIZARD_OPTION) :]
        data_msg = dict(callback_query_id=callback_id, show_alert=False)
        answer_callback_serv = self._bot_notifier + "/answer_callback_query"
        if option == "reset":
            self._bot_wizstack[user_id] = []
            self.log("HASSWIZ RESET", log=LOGGER)
            self.call_service(
                answer_callback_serv,
                message="Reset wizard, start again",
                **data_msg,
            )
        elif option == "back":
            self._bot_wizstack[user_id] = self._bot_wizstack[user_id][:-1]
            message = "Back to: {}".format(self._bot_wizstack[user_id])
            self.log(
                "HASSWIZ BACK --> {}".format(self._bot_wizstack[user_id]),
                log=LOGGER,
            )
            self.call_service(
                answer_callback_serv, message=message, **data_msg
            )
        elif option == "exit":
            self._bot_wizstack[user_id] = []
            self.log("HASSWIZ EXIT", log=LOGGER)
            self.call_service(
                answer_callback_serv, message="Bye bye...", **data_msg
            )
            self.call_service(
                self._bot_notifier + "/send_message",
                target=user_id,
                **INIT_MESSAGE,
            )
            return
        else:
            self._bot_wizstack[user_id].append(option)
            if len(self._bot_wizstack[user_id]) == len(HASSWIZ_STEPS):
                # Try to exec command:
                service, operation, entity_id = self._bot_wizstack[user_id]
                self._bot_wizstack[user_id].pop()
                entity = "{}.{}".format(service, entity_id)
                # CALLING SERVICE / GET STATES
                if (service in ["switch", "light", "input_boolean"]) and (
                    operation in ["turn_on", "turn_off"]
                ):
                    message = "Service called: {}/{}/{}"
                    message = message.format(service, operation, entity_id)
                    self.log(
                        'HASSWIZ: CALLING SERVICE "{}". Stack: {}'.format(
                            message, self._bot_wizstack[user_id]
                        ),
                        log=LOGGER,
                    )
                    self.call_service(
                        "{}/{}".format(service, operation), entity_id=entity
                    )
                    self.call_service(
                        answer_callback_serv, message=message, **data_msg
                    )
                elif operation in ["state", "attributes"]:
                    if operation == "state":
                        data = self.get_state(entity)
                    else:
                        data = self.get_state(entity, attribute="attributes")
                    self.log(
                        "HASSWIZ STATE DATA -> {}/{}/{} -> {}".format(
                            service, operation, entity_id, data
                        ),
                        log=LOGGER,
                    )
                    message = "{} {}: -> {}".format(
                        entity_id, operation, str(data)
                    )
                    self.call_service(
                        answer_callback_serv, message=message, **data_msg
                    )
                else:
                    comb_err = "{}/{}/{}".format(service, operation, entity_id)
                    message = "Combination *not implemented* -> "
                    message += _clean(comb_err)
                    self.log(
                        "ERROR: COMBINATION NOT IMPLEMENTED -> {}".format(
                            comb_err
                        ),
                        level="warning",
                        log=LOGGER,
                    )
                    self.call_service(
                        answer_callback_serv, message=message, **data_msg
                    )
                    return
                return
            else:
                # Notificación de respuesta:
                message = "Option selected: {}".format(option)
                self.log(message, log=LOGGER)
                self.call_service(
                    answer_callback_serv, message=message, **data_msg
                )
        # Show next wizard step
        try:
            wiz_step = HASSWIZ_STEPS[len(self._bot_wizstack[user_id])]
        except IndexError:
            self.log(
                "HASS WIZ INDEX ERROR: stack={}, max={}. Reseting stack".format(
                    len(self._bot_wizstack[user_id]), len(HASSWIZ_STEPS)
                ),
                log=LOGGER,
            )
            self._bot_wizstack[user_id] = []
            wiz_step = HASSWIZ_STEPS[0]
        wiz_step_text = wiz_step["question"]
        if ("{}" in wiz_step_text) and self._bot_wizstack[user_id]:
            wiz_step_text = wiz_step_text.format(
                "/".join(self._bot_wizstack[user_id])
            )

        wiz_step_inline_kb = wiz_step["options"]
        if wiz_step_inline_kb is None:
            # Get options from HASS, filtering with stack opts
            d_entities_options = self._hass_entities[
                self._bot_wizstack[user_id][0]
            ]
            wiz_step_inline_kb = []
            wiz_step_inline_kb_row = []
            for i, (key, fn) in enumerate(d_entities_options.items()):
                btn = (fn, "{}{}".format(COMMAND_WIZARD_OPTION, key))
                wiz_step_inline_kb_row.append(btn)
                if i % 3 == 2:
                    wiz_step_inline_kb.append(wiz_step_inline_kb_row)
                    wiz_step_inline_kb_row = []
            if wiz_step_inline_kb_row:
                wiz_step_inline_kb.append(wiz_step_inline_kb_row)
            wiz_step_inline_kb.append(HASSWIZ_MENU_ACTIONS)

        self.call_service(
            self._bot_notifier + "/edit_message",
            message=wiz_step_text,
            chat_id=user_id,
            message_id=msg_origin["message_id"],
            inline_keyboard=wiz_step_inline_kb,
        )

    # noinspection PyUnusedLocal
    def receive_telegram_event(self, event_id, payload_event, *args):
        """Event listener for Telegram events."""
        self.log(
            'TELEGRAM NOTIFICATION: "{}", payload={}'.format(
                event_id, payload_event
            ),
            level=LOG_LEVEL,
            log=LOGGER,
        )
        if "chat_id" in payload_event:
            user_id = payload_event["chat_id"]
        else:
            user_id = payload_event["user_id"]
        if event_id == "telegram_command":
            command = payload_event["command"].replace(self._bot_name, "")
            cmd_args = payload_event["args"] or ""
            self.process_telegram_command(command, cmd_args, user_id)
        elif event_id == "telegram_text":
            text = payload_event["text"]
            if text.startswith("http") and len(text.split()) == 1:
                # Links as messages are played in Kodi as VIDEO files
                self.play_url_in_media_player(user_id, text, use_kodi=True)
            else:
                msg = "TEXT RECEIVED: ```\n{}\n```".format(text)
                self.log("TELEGRAM TEXT: " + str(text), log=LOGGER)
                self.call_service(
                    self._bot_notifier + "/send_message",
                    target=user_id,
                    message=msg,
                )
        else:
            assert event_id == "telegram_callback"
            msg_origin = payload_event["message"]
            data_callback = payload_event["data"]
            callback_id = payload_event["id"]
            # callback_chat_instance = payload_event['chat_instance']
            user_id = msg_origin["chat"]["id"]

            # Tipo de pulsación (wizard vs simple command):
            if data_callback.startswith(COMMAND_PREFIX):  # exec simple command
                cmd = data_callback.split(" ")
                command, cmd_args = cmd[0], cmd[1:]
                self.log(
                    "CALLBACK REDIRECT TO COMMAND RESPONSE: "
                    'cmd="{}", args="{}", callback_id={}'.format(
                        command, cmd_args, callback_id
                    ),
                    level=LOG_LEVEL,
                    log=LOGGER,
                )
                self.process_telegram_command(
                    command, cmd_args, user_id, callback_id=callback_id
                )
            elif data_callback.startswith(COMMAND_WIZARD_OPTION):  # Wizard
                self.process_telegram_wizard(
                    msg_origin, data_callback, user_id, callback_id
                )
            else:  # WTF?
                rand_msg_mask = TELEGRAM_UNKNOWN[
                    randrange(len(TELEGRAM_UNKNOWN))
                ]
                self.log(
                    "CALLBACK RESPONSE NOT IMPLEMENTED: "
                    + rand_msg_mask.format(data_callback),
                    log=LOGGER,
                )
                self.call_service(
                    self._bot_notifier + "/send_message",
                    target=user_id,
                    keyboard=TELEGRAM_KEYBOARD,
                    message=rand_msg_mask.format(data_callback),
                )

    def frontend_notif(
        self, action_name, msg_origin, mask=DEFAULT_NOTIF_MASK, title=None
    ):
        """Set a persistent_notification in frontend."""
        message = mask.format(self.datetime(), msg_origin)
        title = action_name if title is None else title
        self.persistent_notification(message, title=title, id=action_name)

    def _turn_off_lights_and_appliances(self, turn_off_heater=False):
        self.turn_off("group.all_lights", transition=2)
        # self.turn_off("switch.calefactor")
        # self.turn_off("switch.cocina")
        self.turn_off("switch.altavoz")
        self.turn_off("media_player.kodi_tv")
        # self.turn_off("switch.estudio_light_relay")
        # self.turn_off("switch.new_switch_2")
        self.turn_off("switch.03200296dc4f22293a7f")
        if turn_off_heater:
            self.turn_off("switch.calentador")

    def response_to_action(self, action, origin, telegram_target=None):
        """Respond to defined action events."""
        if telegram_target is None:
            action_msg_log = '*iOS Action "{}" received. '.format(action)
        else:
            action_msg_log = "*Action {}* received: ".format(action)
        # AWAY category
        if action == "ALARM_ARM_NOW":  # Activar alarma
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_ON,
                title="Activación remota de alarma",
            )
            self._turn_off_lights_and_appliances()
            self.select_option(
                "input_select.alarm_mode", option="Fuera de casa"
            )
            action_msg_log += 'ALARM ON, MODE "Fuera de casa"'
        elif action == "ALARM_HOME":  # Activar vigilancia
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_HOME,
                title="Activación remota de vigilancia",
            )
            self._turn_off_lights_and_appliances()
            self.select_option("input_select.alarm_mode", option="En casa")
            action_msg_log += 'ALARM MODE "En casa"'
        elif action == "LIGHTS_OFF":  # Apagar luces
            self._turn_off_lights_and_appliances()
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_LIGHTS_OFF,
                title="Apagado de luces",
            )
            action_msg_log += "APAGANDO LUCES"

        # INHOME category
        elif action == "WELCOME_HOME":  # Alarm OFF, lights ON
            self.select_option(
                "input_select.alarm_mode", option="Desconectada"
            )
            self.turn_on("switch.cocina")
            self.call_service(
                "light/hue_activate_scene",
                group_name="Salón",
                scene_name="Semáforo",
            )
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_OFF,
                title="Llegando a casa, luces ON",
            )
            action_msg_log += 'ALARM OFF. Kitchen ON, "Semáforo"("Salón")'
            self.light_flash(XY_COLORS["green"], persistence=2, n_flashes=2)
        elif action == "WELCOME_HOME_TV":  # Alarm OFF, lights ON
            self.select_option(
                "input_select.alarm_mode", option="Desconectada"
            )
            self.turn_on("script.play_kodi_pvr")
            self.call_service(
                "light/hue_activate_scene",
                group_name="Salón",
                scene_name="Aurora boreal",
            )
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_OFF,
                title="Llegando a casa, tele ON",
            )
            action_msg_log += 'ALARM OFF. TV ON, "Aurora boreal"("Salón")'
            self.light_flash(XY_COLORS["green"], persistence=2, n_flashes=2)
        elif action == "IGNORE_HOME":  # Reset del estado de alarma
            self.fire_event("reset_alarm_state")
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_RESET,
                title="Ignorando presencia",
            )
            action_msg_log += "reset_alarm_state & alarm continues ON"

        elif action == "ALARM_SILENT":  # Silenciar alarma (sólo la sirena)
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_SILENT,
                title="Sirena OFF",
            )
            self.fire_event("silent_alarm_state")
            action_msg_log += "SIRENA OFF"
        elif action == "ALARM_RESET":  # Ignorar armado y resetear
            self.fire_event("reset_alarm_state")
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_RESET,
                title="Ignorando presencia",
            )
            action_msg_log += "reset_alarm_state & alarm continues ON"
        elif action == "ALARM_CANCEL":  # Desconectar alarma
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARM_OFF,
                title="Desconexión de Alarma",
            )
            self.select_option(
                "input_select.alarm_mode", option="Desconectada"
            )
            action_msg_log += "ALARM MODE OFF"
            self.light_flash(XY_COLORS["green"], persistence=2, n_flashes=5)

        # CONFIRM category
        elif action == "CONFIRM_OK":  # Validar
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_LAST_VALIDATION,
                title="Validación",
            )
            action_msg_log += "Confirmation received"
            self.light_flash(XY_COLORS["yellow"], persistence=3, n_flashes=1)

        # KODIPLAY category
        elif action == "LIGHTS_ON":  # Lights ON!
            self.frontend_notif(
                action, origin, mask=NOTIF_MASK_LIGHTS_ON, title="Lights ON!"
            )
            self.call_service(
                "input_number/set_value",
                entity_id="input_number.light_main_slider_salon",
                value=254,
            )
            self.call_service(
                "light/turn_on", entity_id="light.salon", brightness=255
            )
            action_msg_log += "LIGHTS ON: LIGHT MAIN SLIDER SALON 254"
        elif action == "TV_NIGHT_MODE":
            self.select_option(
                "input_select.salon_light_scene", option="TV Night"
            )
            action_msg_log += "TV_NIGHT_MODE"
            self.light_flash(XY_COLORS["blue"], persistence=2, n_flashes=2)
        elif action == "COVERS_DOWN":
            # Set cover position:
            position1 = int(
                self.get_state(
                    "cover.sonoff_cover_ventanal", attribute="current_position"
                )
            )
            if position1 > 50:
                self.call_service(
                    "cover/set_position",
                    entity_id="cover.sonoff_cover_ventanal",
                    position=20,
                )
            elif position1 >= 20:
                self.call_service(
                    "cover/close_cover",
                    entity_id="cover.sonoff_cover_ventanal",
                )
            position2 = int(
                self.get_state(
                    "cover.sonoff_cover_puerta_terraza",
                    attribute="current_position",
                )
            )
            if position2 > 70:
                self.call_service(
                    "cover/set_position",
                    entity_id="cover.sonoff_cover_puerta_terraza",
                    position=70,
                )
            action_msg_log += "COVERS_DOWN"
            self.light_flash(XY_COLORS["violet"], persistence=2, n_flashes=2)

        # elif action == 'HYPERION_TOGGLE':  # Toggle Ambilight
        #     self.frontend_notif(action, origin,
        #                         mask=NOTIF_MASK_TOGGLE_AMB,
        #                         title="Toggle Ambilight")
        #     self.toggle("switch.toggle_kodi_ambilight")
        #     action_msg_log += 'TOGGLE KODI AMBILIGHT'
        #     self.light_flash(XY_COLORS['blue'], persistence=2, n_flashes=2)
        # elif action == 'HYPERION_CHANGE':  # Change Ambilight conf
        #     self.frontend_notif(action, origin,
        #                         mask=NOTIF_MASK_TOGGLE_AMB_CONF,
        #                         title="Cambio de modo Ambilight")
        #     self.toggle("switch.toggle_config_kodi_ambilight")
        #     action_msg_log += 'CHANGE AMBILIGHT CONF'
        #     self.light_flash(XY_COLORS['violet'], persistence=2, n_flashes=2)

        # Air purifier commands
        elif action == "PURIFIER_SILENT":  # Fan to silent mode
            self.call_service(
                "fan/set_speed",
                entity_id="fan.airpurifier_office",
                speed="Silent",
            )
            action_msg_log += f"Set Air purifier in silent mode"
        elif action == "PURIFIER_SET_LEVEL":  # Fan to fixed speed
            level_ap = 6
            self.call_service(
                "fan/xiaomi_miio_set_favorite_level",
                entity_id="fan.airpurifier_office",
                level=level_ap,
            )
            self.call_service(
                "fan/set_speed",
                entity_id="fan.airpurifier_office",
                speed="Favorite",
            )
            action_msg_log += f"Set Air purifier to fixed speed: {level_ap}"
        elif action == "PURIFIER_OFF":  # Fan off
            self.turn_off("fan.airpurifier_office")
            action_msg_log += f"Turn off Air purifier"

        # ALARMCLOCK category
        elif action == "INIT_DAY":  # Luces Energy + Calefactor!
            self.frontend_notif(action, origin, mask=NOTIF_MASK_INIT_DAY)
            self.call_service(
                "light/hue_activate_scene",
                group_name="Dormitorio",
                scene_name="Energía",
            )
            self.turn_on("switch.calefactor")
            action_msg_log += "A NEW DAY STARTS WITH A WARM SHOWER"
        elif action == "POSTPONE_ALARMCLOCK":  # Postponer despertador
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_POSTPONE_ALARMCLOCK,
                title="Posponer despertador",
            )
            self.turn_off("input_boolean.manual_trigger_lacafetera")
            action_msg_log += "Dormilón!"
            self.fire_event("postponer_despertador", jam="true")
        elif action == "ALARMCLOCK_OFF":  # Luces Energy
            self.frontend_notif(
                action,
                origin,
                mask=NOTIF_MASK_ALARMCLOCK_OFF,
                title="Despertador apagado",
            )
            self.turn_off("input_boolean.manual_trigger_lacafetera")
            action_msg_log += "Apagado de alarma"

        # Unrecognized cat
        else:
            action_msg_log += "WTF: origin={}".format(origin)
            self.frontend_notif(action, origin)

        self.log(action_msg_log, log=LOGGER)
