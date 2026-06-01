# Comandos del InSim Bot

A continuación se muestra la lista de comandos disponibles en el chat del juego al jugar en un servidor equipado con el bot de **LFS Open Ranking System**.

> [!TIP] Personalización de Comandos
> Ten en cuenta que **esta es la lista de comandos por defecto**. Como el bot es de código abierto y cada servidor lo aloja de forma independiente, **los administradores del servidor tienen total libertad para cambiar los nombres de los comandos** usando el sistema de *Alias* en su archivo `config.json`. 
> Por ejemplo, un servidor podría configurar `!votar` en lugar de `!vote`, o desactivar algunos comandos por completo.

---

## 🏁 Cuenta y Generales
- `!register` o `!webpass`: Solicita un código único para vincular tu cuenta de LFS con la web de LFS Open Ranking System.
- `!lang <es/en>`: Cambia el idioma en el que el bot te habla por privado.
- `!help`: Muestra un menú de ayuda resumido en el juego.
- `!web` o `!website`: Muestra el enlace a la web oficial del ranking.

## 📊 Estadísticas y Ránking
- `!stats`, `!rank` o `!elo`: Muestra tu posición global, ELO actual y victorias.
- `!top`: Muestra el Top 10 de pilotos con más ELO a nivel mundial.
- `!topwins`: Muestra los pilotos con mayor cantidad de victorias.
- `!topcars`: Muestra cuáles son los coches más usados/populares en la red.
- `!nations`: Muestra la distribución demográfica de los pilotos por país.

## ⏱️ Tiempos y Récords
- `!mypb`: Muestra tu Récord Personal (PB) en la combinación actual de circuito y coche.
- `!pb [circuito] [coche]`: Busca tu PB en una combinación específica.
- `!sr` o `!wr`: Muestra el Récord del Servidor (o Récord Mundial) actual.
- `!track` o `!tr`: Muestra detalles del circuito actual y los coches permitidos.

## 🤝 Sistema de Equipos (Teams)
- `!teams`: Muestra el ranking global de equipos (por puntos).
- `!team create <nombre>`: Crea un nuevo equipo y te asigna como líder.
- `!team join <nombre>`: Envía una solicitud para unirte a un equipo existente.
- `!team leave`: Abandonas tu equipo actual.
- `!team info`: Muestra información, miembros y puntos de tu equipo actual.
- `!team pending`: (Líderes) Muestra las solicitudes de unión pendientes.
- `!team accept/decline <usuario>`: (Líderes) Acepta o rechaza una solicitud.
- `!team kick <usuario>`: (Líderes) Expulsa a un miembro del equipo.
- `!team promote <usuario>`: (Líderes) Traspasa el liderazgo a otro miembro.

## 🗳️ Votaciones
- `!vote <track/cars/kick/restart>`: Inicia una votación para cambiar de pista, coches, expulsar a un jugador o reiniciar la carrera.
- `!y` / `!n`: Vota a favor (Yes) o en contra (No) en una votación activa. *(Dependiendo de la configuración del servidor, las votaciones también se pueden hacer con botones en pantalla).*
- `!badcombo`: Vota para saltar la combinación actual si es injugable.

## ⚙️ Administradores
*Estos comandos solo funcionan si tu nombre de usuario está en la `admin_list` del `config.json` del servidor local.*
- `!admin`: Abre el panel de administración InSim interactivo.
- `!random`: Fuerza un cambio a una combinación aleatoria de circuito y coches.
- `!allcars`: Permite todos los coches en el circuito actual.
- `!setmod <mod>`: Carga un mod específico.
- `!setcars <coches>`: Cambia los coches permitidos manualmente.
