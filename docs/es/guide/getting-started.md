# ¿Qué es LFS Open Ranking System?

LFS Open Ranking System es una plataforma diseñada para **Live for Speed** que introduce un sistema de puntuación competitivo global (ELO) y un registro permanente e inmutable de Récords Personales (PBs) a través de múltiples servidores alrededor del mundo.

## ¿Por qué unificar?

Tradicionalmente, cada servidor de LFS tiene sus propios trackers locales, lo que divide a la comunidad y hace imposible saber quién es realmente el mejor piloto en una combinación de coche y circuito concreta. 

Nuestro sistema soluciona esto utilizando un modelo **P2P (Peer-to-Peer) descentralizado**:
- **Consenso Global**: Todos los servidores adheridos a la red envían los resultados verificados a los Nodos Validadores.
- **Transparencia**: Los validadores cruzan las firmas criptográficas para asegurar que nadie ha manipulado los tiempos.
- **Base de datos compartida**: Todo el mundo contribuye al mismo historial inmutable.

## Funcionalidades Principales

- **Sistema ELO Global**: Un sistema de emparejamiento y ranking al estilo del Ajedrez o los eSports modernos. Si ganas a gente con más ELO, subes más rápido; si pierdes contra gente de menor nivel, bajas.
- **Récords Personales (PBs)**: Da igual en qué servidor estés corriendo. Si haces tu mejor tiempo personal, quedará registrado para siempre en la red y será accesible mediante el comando `!pb`.
- **Multiclase y Mods**: El sistema soporta de forma nativa mods y rotaciones multiclase aleatorias para asegurar que haya variedad.

## Primeros pasos para Pilotos

1. Entra a un servidor de LFS compatible (Busca servidores que tengan la etiqueta *LFS Rank*).
2. Escribe `!register` en el chat del juego.
3. El servidor te responderá por mensaje privado con un **código de verificación** único.
4. Ve a nuestra web (sección **Login / Register**) y usa ese código para terminar de registrar tu cuenta global.
5. ¡Compite! A partir de ese momento, tu ELO y tus PBs se actualizarán automáticamente tras cada carrera verificada. Podrás consultar tu progreso tanto en tu perfil web como dentro del juego usando el comando `!stats`.
