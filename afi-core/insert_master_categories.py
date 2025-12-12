from db_ops import execute_insert, execute_query

def insert_default_master_categories():
    print("Ensuring default master categories exist...")
    categories = [
        ("Vivienda", "fixed"),
        ("Mercado", "variable"),
        ("Transporte", "variable"),
        ("Ocio", "variable"),
        ("Ahorro", "savings")
    ]
    
    for name, type in categories:
        # Check if category already exists
        existing = execute_query("SELECT id FROM master_categories WHERE name = %s", (name,), fetch_one=True)
        if not existing:
            execute_insert(
                "INSERT INTO master_categories (name, type) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                (name, type)
            )
            print(f"  Inserted category: {name} ({type})")
        else:
            print(f"  Category '{name}' already exists.")

if __name__ == "__main__":
    insert_default_master_categories()