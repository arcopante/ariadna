# Cómo contribuir

¡Gracias por tu interés en ARIADNA! Este es un proyecto de investigación abierto
sobre IA en entornos de mundo real con hardware accesible. Cualquier contribución,
grande o pequeña, es bienvenida.

## Formas de contribuir

- **Reportar bugs** — Abre un issue describiendo el problema, tu hardware y los logs relevantes.
- **Proponer mejoras** — Abre un issue con la etiqueta `enhancement` antes de ponerte a programar.
- **Enviar código** — Fork + rama + Pull Request (ver flujo abajo).
- **Documentar** — Mejoras al README, tutoriales, diagramas, vídeos.
- **Compartir experimentos** — Si pruebas algo nuevo (otro modelo, otro sensor, otro robot), abre un issue o PR contando qué aprendiste.

## Flujo de trabajo con Git

```bash
# 1. Fork del repositorio en GitHub

# 2. Clonar tu fork
git clone https://github.com/TU_USUARIO/ariadna-robot.git
cd ariadna-robot

# 3. Crear rama con nombre descriptivo
git checkout -b feature/modulo-voz
git checkout -b fix/watchdog-timeout
git checkout -b docs/tutorial-instalacion

# 4. Hacer cambios, commits pequeños y descriptivos
git add .
git commit -m "feat: añadir módulo de voz con Whisper tiny"

# 5. Push y Pull Request hacia la rama main del repositorio original
git push origin feature/modulo-voz
```

## Convención de commits

Usamos [Conventional Commits](https://www.conventionalcommits.org/):

| Prefijo    | Cuándo usarlo                                      |
|------------|----------------------------------------------------|
| `feat:`    | Nueva funcionalidad                                |
| `fix:`     | Corrección de bug                                  |
| `docs:`    | Solo documentación                                 |
| `refactor:`| Refactorización sin cambio de comportamiento       |
| `test:`    | Añadir o corregir tests                            |
| `chore:`   | Tareas de mantenimiento (deps, CI, etc.)           |
| `hw:`      | Cambios específicos de hardware o firmware Arduino |

## Estilo de código

- Python: seguir PEP 8. Se puede usar `black` para formatear automáticamente.
- Arduino: estilo del proyecto existente (comentarios en español, constantes en MAYÚSCULAS).
- Docstrings en español para mantener coherencia con el README.

## Hardware soportado

El proyecto está diseñado para Makeblock Ranger / generación anterior + Arduino + Odroid-C2,
pero aceptamos PRs que añadan soporte para:
- Otros robots Makeblock (mBot, mBot2)
- Otras SBC (Raspberry Pi 4/5, Jetson Nano)
- Otros microcontroladores compatibles con Makeblock

Si añades soporte para nuevo hardware, documenta los cambios necesarios en el README.

## Preguntas

Abre un issue con la etiqueta `question`. No hay preguntas tontas.
