# What is LFS Open Ranking System?

LFS Open Ranking System is a platform designed for **Live for Speed** that introduces a global competitive scoring system (ELO) and a permanent, immutable record of Personal Bests (PBs) across multiple servers around the world.

## Why unify?

Traditionally, each LFS server has its own local trackers, which divides the community and makes it impossible to know who is truly the best driver in a specific car and track combination.

Our system solves this by using a **decentralized P2P (Peer-to-Peer) model**:
- **Global Consensus**: All servers connected to the network send their verified results to the Validator Nodes.
- **Transparency**: Validators cross-check cryptographic signatures to ensure no one has tampered with the lap times.
- **Shared Database**: Everyone contributes to the same immutable history.

## Main Features

- **Global ELO System**: A matchmaking and ranking system similar to Chess or modern eSports. If you beat players with higher ELO, you climb faster; if you lose against lower-level players, you drop.
- **Personal Bests (PBs)**: It doesn't matter which server you are racing on. If you set your best personal time, it will be permanently recorded on the network and accessible via the `!pb` command.
- **Multiclass & Mods**: The system natively supports mods and random multiclass rotations to ensure variety.

## Getting Started for Drivers

1. Join a compatible LFS server (Look for servers with the *LFS Rank* tag).
2. Type `!register` in the in-game chat.
3. The server will reply via private message with a unique **verification code**.
4. Go to our website (**Login / Register** section) and use that code to finish registering your global account.
5. Race! From that moment on, your ELO and PBs will automatically update after every verified race. You can check your progress both on your web profile and in-game using the `!stats` command.
