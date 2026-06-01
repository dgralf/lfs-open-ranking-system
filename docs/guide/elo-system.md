# The ELO System

The **LFS Open Ranking System** uses a multiplayer adaptation of the classic ELO rating system (originally designed for chess). Instead of calculating ELO as multiple isolated 1v1 duels, the algorithm processes the race as a global free-for-all matchup.

---

## 🏎️ Multi-class Races
**The system natively supports multi-class racing.**

When a race finishes, the server groups drivers by their vehicle category (e.g., TBO, GTR, GTI). The system compares your results **solely and exclusively with drivers who were driving cars in your same category**. 

- If you race with a slow car (e.g., UF1000) against fast cars (e.g., XF GTR), **you will not be penalized** for finishing behind them in the overall standings.
- Your ELO variation will only be based on whether you beat the other UF1000s in your class.
- The server maintains an independent ELO for you in each category you compete in, and your global ELO is the average of all your categories.

---

## 📐 Mathematical Formulas

The logic behind the point distribution is based on comparing your **Actual Performance ($S_i$)** against your **Expected Performance ($\mathbb{E}_i$)**.

### 1. Actual Performance ($S_i$)
Your actual score is calculated based on your finishing position ($pos_i$) relative to the total number of drivers ($n$). The winner gets 1.0, the last gets 0.0, and the rest get fractional values.

$$ S_i = \frac{n - pos_i}{n - 1} $$

### 2. Expected Performance ($\mathbb{E}_i$)
We calculate the probability of you finishing ahead of each of the other rivals ($j$) based on the difference in your current ELOs ($E_i$ vs $E_j$). Then we average those probabilities.

$$ \mathbb{E}_i = \frac{1}{n-1} \sum_{j \neq i} \frac{1}{1 + 10^{(E_j - E_i)/400}} $$

### 3. ELO Variation ($\Delta E_i$)
Finally, the difference between your actual and expected performance is multiplied by the volatility factor (K-Factor) to determine how many points you gain or lose.

$$ \Delta E_i = K \times (S_i - \mathbb{E}_i) $$
*Note: The system currently uses a constant **$K = 32$** for all races.*

---

## 🧠 What does this mean in practice?

- **Beating higher ELO drivers:** If you beat drivers who have more ELO than you, your Expected Performance was low, so the point gain will be massive.
- **Losing against lower ELO drivers:** If you finish behind players who have less ELO, the system expected you to win. Your point loss will be severe.
- **The $n$ factor:** The more players on the grid, the more total points are at stake and the smoother the distribution curve is for middle positions.
- **Rage-quits:** Quitting or disconnecting from the race will automatically place you in the last position of your class, resulting in a drastic ELO loss. Always finish the race!
