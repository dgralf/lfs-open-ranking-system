# Custom InSim and Total Freedom

One of the biggest advantages of integrating your server into the **LFS Open Ranking System** ecosystem is that **we do not force you to use a closed-source bot**.

## You Have Absolute Control

Your server hosts its own local Bot Client (`system.py`). Since it is an open-source Python script that you download and configure yourself, you have total freedom to:
- **Modify messages**: Change all the texts the bot sends to the screen, buttons, and languages.
- **Add custom commands**: Write your own code to detect chat commands (e.g., `!rules`, `!discord`, or penalty scripts).
- **Advanced InSim Logic**: Control pit stops, starting grid layouts, drift scoring scripts, or anything else the InSim protocol offers.

> [!TIP]
> **The only strict requirement** is to keep intact the section of the bot that packages the race results (`IS_RES`) into the standard JSON and POSTs it to the Validator Node API (`/ingest`), signed digitally with your locally generated Ed25519 key.

As long as your data packet maintains the correct format and is sent to the Validator Node with your authentication key, your server will continue to contribute to the global ELO. Feel free to fork our bot and adapt it 100% to your community's needs!
