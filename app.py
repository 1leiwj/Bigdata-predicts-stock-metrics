from flask import Flask, render_template
from flask_socketio import SocketIO
from consumer import start_consumer
import threading

app = Flask(__name__)
socketio = SocketIO(app)

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    print('Client connected')

def run_consumer():
    start_consumer(socketio)

if __name__ == '__main__':
    # 启动消费者线程
    consumer_thread = threading.Thread(target=run_consumer)
    consumer_thread.daemon = True
    consumer_thread.start()
    
    # 启动Flask应用
    socketio.run(app, debug=True)
