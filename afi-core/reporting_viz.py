import matplotlib.pyplot as plt
import io

def generate_spending_pie_chart(data: dict, title: str = "Distribución de Gastos"):
    """
    Genera un gráfico de torta en memoria (PNG).
    data: dict {'Categoria': monto, ...}
    """
    if not data:
        return None

    # Limpiar datos (eliminar negativos o ceros si es torta)
    labels = []
    sizes = []
    for k, v in data.items():
        val = abs(v)
        if val > 0:
            labels.append(k)
            sizes.append(val)

    if not sizes:
        return None

    plt.figure(figsize=(8, 8))
    # Colores elegantes
    colors = plt.cm.Pastel1(range(len(labels)))
    
    plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140, colors=colors)
    plt.title(title)
    plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight')
    buf.seek(0)
    plt.close() # Liberar memoria
    return buf

def generate_spending_bar_chart(data: dict, title: str = "Gastos por Categoría"):
    """
    Genera un gráfico de barras.
    """
    if not data:
        return None

    categories = list(data.keys())
    values = [abs(v) for v in data.values()]

    plt.figure(figsize=(10, 6))
    plt.bar(categories, values, color='skyblue')
    plt.title(title)
    plt.xlabel('Categoría')
    plt.ylabel('Monto')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()
    return buf
