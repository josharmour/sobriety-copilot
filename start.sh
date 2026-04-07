#!/bin/bash
# Sobriety Copilot — startup script
# Ensures Ollama and the Flask server are running

cd /home/joshu/repos/sobriety-copilot

WSL_IP=$(hostname -I | awk '{print $1}')
OLLAMA_HOST="172.20.48.1"
PORT=5000
LLM_MODEL="gemma4:e2b"

echo "=== Sobriety Copilot Startup ==="
echo ""

# 1. Check Ollama (start it if needed)
echo -n "Checking Ollama... "
if curl -s --connect-timeout 3 "http://$OLLAMA_HOST:11434/api/tags" > /dev/null 2>&1; then
    MODEL=$(curl -s "http://$OLLAMA_HOST:11434/api/ps" 2>/dev/null | python3 -c "import sys,json; models=json.load(sys.stdin).get('models',[]); print(models[0]['name'] if models else 'none')" 2>/dev/null)
    echo "running (model: $MODEL)"
else
    echo "not running, starting..."
    powershell.exe -Command "Start-Process 'C:\Users\joshu\AppData\Local\Programs\Ollama\ollama app.exe'" 2>/dev/null
    echo -n "  Waiting for Ollama"
    for i in $(seq 1 30); do
        if curl -s --connect-timeout 2 "http://$OLLAMA_HOST:11434/api/tags" > /dev/null 2>&1; then
            echo " ready!"
            break
        fi
        echo -n "."
        sleep 1
    done
    if ! curl -s --connect-timeout 2 "http://$OLLAMA_HOST:11434/api/tags" > /dev/null 2>&1; then
        echo " FAILED"
        echo "  Could not start Ollama. Start it manually on Windows, then re-run."
        echo "  Press Enter to exit..."
        read
        exit 1
    fi
fi

# 2. Pre-warm model into VRAM
echo -n "Loading $LLM_MODEL into VRAM... "
LOADED=$(curl -s "http://$OLLAMA_HOST:11434/api/ps" 2>/dev/null | python3 -c "import sys,json; models=json.load(sys.stdin).get('models',[]); print('yes' if any('$LLM_MODEL' in m['name'] for m in models) else 'no')" 2>/dev/null)
if [ "$LOADED" = "yes" ]; then
    echo "already loaded"
else
    curl -s "http://$OLLAMA_HOST:11434/api/generate" -d "{\"model\":\"$LLM_MODEL\",\"prompt\":\"\",\"keep_alive\":-1}" > /dev/null 2>&1
    echo "done"
fi

# 3. Check/start Flask server
echo -n "Checking Flask server... "
if curl -s --connect-timeout 3 "http://localhost:$PORT/" > /dev/null 2>&1; then
    echo "already running on port $PORT"
else
    echo "starting..."
    source /home/joshu/repos/sobriety-copilot/venv/bin/activate
    export LLM_MODEL
    nohup python -m src.server > /tmp/sobriety-server.log 2>&1 &
    SERVER_PID=$!
    echo -n "  Waiting for server to load"
    for i in $(seq 1 30); do
        if curl -s --connect-timeout 2 "http://localhost:$PORT/" > /dev/null 2>&1; then
            echo " ready! (PID: $SERVER_PID)"
            break
        fi
        echo -n "."
        sleep 1
    done
    if ! curl -s --connect-timeout 2 "http://localhost:$PORT/" > /dev/null 2>&1; then
        echo " FAILED"
        echo "  Check /tmp/sobriety-server.log for errors"
        echo "  Press Enter to exit..."
        read
        exit 1
    fi
fi

# 4. Check port proxy
echo -n "Checking port proxy... "
PROXY_OK=$(powershell.exe -Command "netsh interface portproxy show v4tov4" 2>/dev/null | grep -c "$PORT")
if [ "$PROXY_OK" -gt 0 ]; then
    echo "configured"
else
    echo "setting up..."
    powershell.exe -Command "Start-Process powershell -ArgumentList '-Command','netsh interface portproxy add v4tov4 listenport=$PORT listenaddress=0.0.0.0 connectport=$PORT connectaddress=$WSL_IP' -Verb RunAs -Wait" 2>/dev/null
    echo "  (you may need to approve the admin prompt)"
fi

# 5. Summary
echo ""
echo "=== All Systems Go ==="
echo "  Local:  http://localhost:$PORT"
echo "  LAN:    http://10.0.0.10:$PORT"
echo "  Public: https://sobrietycopilot.com"
echo ""
echo "Server log: /tmp/sobriety-server.log"
echo "Press Enter to exit..."
read
