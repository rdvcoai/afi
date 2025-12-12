import matplotlib.pyplot as plt
import io
import os
import uuid

MEDIA_DIR = "/app/data/media"

def create_spending_chart(data: dict) -> str:
    """
    Genera un gráfico de torta de gastos y devuelve la ruta del archivo.
    data: dict { "Categoria": monto }
    """
    if not data:
        return None

    # Filtrar valores negativos (gastos) y hacerlos positivos para el gráfico
    chart_data = {}
    for k, v in data.items():
        if v < 0:
            chart_data[k] = abs(v)
        elif v > 0:
             # Si vienen positivos (ej. presupuesto), usarlos directo
             chart_data[k] = v

    if not chart_data:
        return None

    plt.figure(figsize=(6, 6))
    plt.pie(chart_data.values(), labels=chart_data.keys(), autopct='%1.1f%%', startangle=140)
    plt.title("Distribución de Gastos")
    plt.tight_layout()

    filename = f"chart_{uuid.uuid4().hex}.png"
    filepath = os.path.join(MEDIA_DIR, filename)
    
    # Asegurar directorio
    os.makedirs(MEDIA_DIR, exist_ok=True)
    
    plt.savefig(filepath)
    plt.close()
    
    return filepath
