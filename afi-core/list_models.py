import os
import google.generativeai as genai

GENAI_KEY = os.getenv("GOOGLE_API_KEY")
if GENAI_KEY:
    genai.configure(api_key=GENAI_KEY)
    print("🔍 Listando modelos disponibles con tu API key:")
    print("=" * 60)

    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"✓ {m.name}")
                print(f"  Display: {m.display_name}")
                print(f"  Methods: {m.supported_generation_methods}")
                print()
    except Exception as e:
        print(f"❌ Error listando modelos: {e}")
else:
    print("❌ No se encontró GOOGLE_API_KEY")
