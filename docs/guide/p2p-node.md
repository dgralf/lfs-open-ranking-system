# P2P Nodes and Decentralization

LFS Open Ranking System operates as a decentralized network of validator nodes. No single server has a monopoly on the truth; for a race to be considered "official" (and affect the global ELO), the race block must be processed and signed by a Validator Node.

## Cryptographic Operation

1. **Local Generation**: The Bot Client detects the end of a race (via `IS_RES` packets for each player through InSim). It generates a raw JSON object with the results.
2. **Secure Transmission**: The Bot Client authenticates using Ed25519 signatures and sends the JSON via HTTP `POST` to its assigned Validator Node (by default, the main LFSRank API).
3. **Node Consensus**: The Validator Node receives the JSON. It verifies that the cryptographic signature matches the Public Key of the claiming server, calculates a **SHA-256 Hash** of the block, and incorporates the `previous_hash` (the hash of the previous race from that same server) to form an unbreakable chain.
4. **Signature**: The Validator Node cryptographically signs the entire package using its Master Key.
5. **P2P Gossiping**: The block, now signed and codified as official, is shared and synchronized with the rest of the P2P node network.

## Transparency and Records

Any node in the network can mathematically verify the legitimacy of past races by checking that the hashes match from start to finish, creating an immutable history of PBs (Personal Bests) and ELO variations.
