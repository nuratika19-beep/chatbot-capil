# main.py
from pyngrok import ngrok
from app import app

def run():
    port = 5000
    public_url = ngrok.connect(port)
    print(f"✅ Aplikasi DISDUKCAPIL siap diakses publik melalui: {public_url}")
    app.run(port=port, debug=False, use_reloader=False)
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5006, debug=True)





 