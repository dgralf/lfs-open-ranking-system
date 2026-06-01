# El Sistema ELO

El **LFS Open Ranking System** utiliza una adaptación multijugador del clásico sistema de puntuación ELO (originalmente diseñado para el ajedrez). En lugar de calcular el ELO como múltiples duelos 1v1 aislados, el algoritmo procesa la carrera como un enfrentamiento global de todos contra todos.

---

## 🏎️ Carreras Multiclase (Multi-class)
**El sistema soporta carreras multiclase de forma nativa.**

Cuando una carrera termina, el servidor agrupa a los pilotos por la categoría de su vehículo (ej. TBO, GTR, GTI). El sistema compara tus resultados **única y exclusivamente con los pilotos que conducían coches de tu misma categoría**. 

- Si corres con un coche lento (ej. UF1000) contra coches rápidos (ej. XF GTR), **no serás penalizado** por terminar detrás de ellos en la general.
- Tu variación de ELO solo se basará en si venciste a los otros UF1000 de tu clase.
- El servidor mantiene un ELO independiente para ti en cada categoría en la que compites, y tu ELO global es el promedio de todas tus categorías.

---

## 📐 Fórmulas Matemáticas

La lógica detrás del reparto de puntos se basa en comparar tu **Rendimiento Real ($S_i$)** contra tu **Rendimiento Esperado ($\mathbb{E}_i$)**.

### 1. Rendimiento Real ($S_i$)
Tu puntuación real se calcula en base a tu posición final ($pos_i$) respecto al número total de pilotos ($n$). El ganador obtiene un 1.0, el último un 0.0, y el resto valores fraccionales.

$$ S_i = \frac{n - pos_i}{n - 1} $$

### 2. Rendimiento Esperado ($\mathbb{E}_i$)
Calculamos la probabilidad de que quedes por delante de cada uno de los demás rivales ($j$) basándonos en la diferencia de vuestros ELOs actuales ($E_i$ vs $E_j$). Luego promediamos esas probabilidades.

$$ \mathbb{E}_i = \frac{1}{n-1} \sum_{j \neq i} \frac{1}{1 + 10^{(E_j - E_i)/400}} $$

### 3. Variación de ELO ($\Delta E_i$)
Finalmente, la diferencia entre tu rendimiento real y el esperado se multiplica por el factor de volatilidad (K-Factor) para determinar cuántos puntos ganas o pierdes.

$$ \Delta E_i = K \times (S_i - \mathbb{E}_i) $$
*Nota: Actualmente el sistema utiliza un **$K = 32$** constante para todas las carreras.*

---

## 🧠 ¿Qué significa esto en la práctica?

- **Vencer a pilotos de mayor ELO:** Si ganas a pilotos que tienen más ELO que tú, tu Rendimiento Esperado era bajo, por lo que la ganancia de puntos será masiva.
- **Perder contra pilotos de menor ELO:** Si quedas por detrás de jugadores que tienen menos ELO, el sistema esperaba que ganaras. Tu pérdida de puntos será severa.
- **El factor $n$:** Cuantos más jugadores haya en la parrilla, más puntos totales hay en juego y más suave es la curva de distribución para los puestos intermedios.
- **Rage-quits:** Abandonar o desconectarte de la carrera te colocará automáticamente en la última posición de tu clase, resultando en una pérdida de ELO drástica. ¡Termina siempre la carrera!
