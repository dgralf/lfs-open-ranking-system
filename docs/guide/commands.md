# InSim Bot Commands

Below is the list of commands available in the in-game chat when playing on a server equipped with the **LFS Open Ranking System** bot.

> [!TIP] Command Customization
> Keep in mind that **this is the default command list**. Because the bot is open-source and each server hosts it independently, **server administrators have full freedom to change command names** using the *Alias* system in their `config.json` file. 
> For example, a server might configure `!votar` instead of `!vote`, or disable some commands entirely.

---

## 🏁 Account and General
- `!register` or `!webpass`: Requests a unique code to link your LFS account with the LFS Open Ranking System website.
- `!lang <es/en>`: Changes the language the bot uses to private message you.
- `!help`: Displays a summarized help menu in-game.
- `!web` or `!website`: Displays the link to the official ranking website.

## 📊 Statistics and Ranking
- `!stats`, `!rank` or `!elo`: Displays your global position, current ELO, and wins.
- `!top`: Displays the Top 10 drivers with the highest ELO worldwide.
- `!topwins`: Displays the drivers with the highest amount of wins.
- `!topcars`: Displays which cars are the most used/popular on the network.
- `!nations`: Displays the demographic distribution of drivers by country.

## ⏱️ Times and Records
- `!mypb`: Displays your Personal Best (PB) on the current track and car combination.
- `!pb [track] [car]`: Searches for your PB on a specific combination.
- `!sr` or `!wr`: Displays the current Server Record (or World Record).
- `!track` or `!tr`: Displays details of the current track and allowed cars.

## 🤝 Team System
- `!teams`: Displays the global team ranking (by points).
- `!team create <name>`: Creates a new team and assigns you as the leader.
- `!team join <name>`: Sends a request to join an existing team.
- `!team leave`: Leaves your current team.
- `!team info`: Displays information, members, and points of your current team.
- `!team pending`: (Leaders) Displays pending join requests.
- `!team accept/decline <user>`: (Leaders) Accepts or declines a request.
- `!team kick <user>`: (Leaders) Kicks a member from the team.
- `!team promote <user>`: (Leaders) Transfers leadership to another member.

## 🗳️ Voting
- `!vote <track/cars/kick/restart>`: Starts a vote to change the track, cars, kick a player, or restart the race.
- `!y` / `!n`: Votes in favor (Yes) or against (No) an active vote. *(Depending on server configuration, voting can also be done via on-screen buttons).*
- `!badcombo`: Votes to skip the current combination if it's unplayable.

## ⚙️ Administrators
*These commands only work if your username is in the `admin_list` of the server's local `config.json`.*
- `!admin`: Opens the interactive InSim admin panel.
- `!random`: Forces a change to a random track and cars combination.
- `!allcars`: Allows all cars on the current track.
- `!setmod <mod>`: Loads a specific mod.
- `!setcars <cars>`: Manually changes the allowed cars.
