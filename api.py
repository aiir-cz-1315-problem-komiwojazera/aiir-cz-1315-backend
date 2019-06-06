from flask import Flask, request, jsonify, make_response, flash, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from functools import wraps
import subprocess
import click
from flask.cli import with_appcontext
import sys
import os
from werkzeug.utils import secure_filename
from rq.job import Job
from worker import conn
from sqlalchemy.orm import relationship
from rq import Worker, Queue, Connection
import redis
import time
import json

UPLOAD_FOLDER = '/home/ubuntu/cloud/backend/aiir-cz-1315-backend/'
#UPLOAD_FOLDER = '/home/kamila/Pulpit/AIIR/backend/aiir-cz-1315-backend/'

app = Flask(__name__, instance_path=UPLOAD_FOLDER)
CORS(app)


ALLOWED_EXTENSIONS = set(['txt'])
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = 'thisissecret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + UPLOAD_FOLDER + '/todo.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['REDIS_URL'] = os.getenv('REDISTOGO_URL', 'redis://localhost:6379')

db = SQLAlchemy(app)
q = Queue(connection=conn, name='waiting_tasks')

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(50), unique=True)
    name = db.Column(db.String(50))
    password = db.Column(db.String(80))
    admin = db.Column(db.Boolean)
    #task = relationship("Task")


#doprowadzić do działania, jeśli chcemy przechowywać wyniki w bazie
'''
class Result(db.Model):
    __tablename__ = 'result'
    id = db.Column(db.Integer, primary_key=True)
    cost = db.Column(db.Integer)
    tsp_path = db.Column(db.String()) #wypisane miasta w kolejnosci odwiedzania?
    # można dołożyć pole task, jeśli chcemy mieć relację w obie strony
'''
class Task(db.Model):
    __tablename__ = 'task'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    user = relationship("User")
    problem_name = db.Column(db.String())
    size = db.Column(db.Integer)
    filename = db.Column(db.String())
    progress = db.Column(db.Integer)
    cost = db.Column(db.Integer)
    tsp_path = db.Column(db.String())
    
    @property
    def serialize(self):
        cost = self.cost
        if cost==None:
            cost="brak wyniku"
        route = self.tsp_path
        if route==None:
            route="brak wyniku"
        return {
            'id' : self.id,
            'name' : self.problem_name,
            'cost' : cost, #self.cost,
            'route' : route, #self.tsp_path,
            'progress' : self.progress
        }
db.create_all()

#odpalanie z konsoli: flask run_worker albo "ogólnie" rqworker waiting_tasks
@click.command('run_worker')
@with_appcontext 
def run_worker():
    redis_url = app.config['REDIS_URL']
    redis_connection = redis.from_url(redis_url)
    with Connection(redis_connection):
        worker = Worker('waiting_tasks')
        worker.work()

app.cli.add_command(run_worker)

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'x-access-token' in request.headers:
            token = request.headers['x-access-token']

        if not token:
            return jsonify({'message' : 'Brak tokena'}), 401

        try: 
            data = jwt.decode(token, app.config['SECRET_KEY'])
            current_user = User.query.filter_by(public_id=data['public_id']).first()
        except:
            return jsonify({'message' : 'Zły token'}), 401

        return f(current_user, *args, **kwargs)

    return decorated

@app.route('/user', methods=['GET'])
@token_required
def get_all_users(current_user):

    if not current_user.admin:
        return jsonify({'message' : 'Nie jesteś adminem, nie możesz tego wykonać'})

    users = User.query.all()

    output = []

    for user in users:
        user_data = {}
        user_data['public_id'] = user.public_id
        user_data['name'] = user.name
        user_data['password'] = user.password
        user_data['admin'] = user.admin
        output.append(user_data)

    return jsonify({'users' : output})

@app.route('/user/<public_id>', methods=['GET'])
@token_required
def get_one_user(current_user, public_id):

    if not current_user.admin:
        return jsonify({'message' : 'Nie jesteś adminem, nie możesz tego wykonać'})

    user = User.query.filter_by(public_id=public_id).first()

    if not user:
        return jsonify({'message' : 'Nie znaleziono użytkownika'})

    user_data = {}
    user_data['public_id'] = user.public_id
    user_data['name'] = user.name
    user_data['password'] = user.password
    user_data['admin'] = user.admin

    return jsonify({'user' : user_data})

@app.route('/user/<public_id>', methods=['PUT'])
@token_required
def promote_user(current_user, public_id):

    if not current_user.admin:
        return jsonify({'message' : 'Nie jesteś adminem, nie możesz tego wykonać'})

    user = User.query.filter_by(public_id=public_id).first()

    if not user:
        return jsonify({'message' : 'Nie znaleziono użytkownika'})

    user.admin = True
    db.session.commit()

    return jsonify({'message' : 'Zmieniono uprawnienia na admina'})

@app.route('/user/<public_id>', methods=['DELETE'])
@token_required
def delete_user(current_user, public_id):

    if not current_user.admin:
        return jsonify({'message' : 'Nie jesteś adminem, nie możesz tego wykonać'})

    user = User.query.filter_by(public_id=public_id).first()

    if not user:
        return jsonify({'message' : 'Nie znaleziono użytkownika'})

    db.session.delete(user)
    db.session.commit()

    return jsonify({'message' : 'Usunięto użytkownika'})

@app.route('/startCalc', methods=['POST'])
#@token_required
def start_calc():#current_user):
    target=os.path.join(app.config['UPLOAD_FOLDER'],'test_docs')
    if not os.path.isdir(target):
        os.mkdir(target)
    file = request.files['file']
    problem_name = request.form['filename']
    user_id = request.form['user']

    if file.filename == '':
            flash('No selected file')
            return redirect('/')
    
    
    if file and allowed_file(file.filename):
        filename = user_id + '.' + problem_name + '.' + secure_filename(file.filename)
        destination = "/".join([target, filename])
        file.save(destination)
    else:
        #to można w jakiejś innej formie przedstawić
        return jsonify({'route' : 'Nieprawidłowy plik'}) 
    with open(destination) as f:
        size = f.readline()
    print(size, file=sys.stdout)
    new_task = Task(user_id=user_id, problem_name=problem_name, \
        filename=destination, size=size, progress=0, tsp_path='Brak danych')
    db.session.add(new_task)
    db.session.commit()
    
    job = q.enqueue_call(
            func=mpi, args=(destination, new_task.id,),
            ttl=-1, timeout=-1
        )
    jsonify({'result' : 'Rozpoczęto obliczenia'})

    while str(job.get_status())!='finished' and str(job.get_status())!='failed':
        time.sleep(0.5)  #
    print(str(job.get_status()), file=sys.stderr)
    if str(job.get_status())=='started':
        return jsonify({'result' : 'Rozpoczęto obliczenia'})
    elif str(job.get_status())=='queued':
        return jsonify({'result' : 'Oczekuje na wykonanie'})
    elif str(job.get_status())=='finished':
        db.session.commit() #TAK, TEN COMMIT MA BYĆ!!!
        task = Task.query.filter_by(id=new_task.id).first()
        return jsonify({'result' : str(task.cost), 'route' : str(task.tsp_path)})
    else: 
        return jsonify({'result' : 'Wystąpił błąd'})

    return jsonify({'result' : str(job.get_status())})
'''    
#    lista = job.result.split('\n')

#    lista3 = lista[0]
#    for miasto in lista[1:-2]:
#        lista3 = lista3 + '-' + miasto
#    return jsonify({'result' : str(lista[-2]), 'route' : str(lista3)})
'''
    
def mpi(filename, task_id):
    #można to bardziej elegancko zrobić, pobierajac w mpi filename jako argument
    #chyba że to koliduje z czymś jeszcze
    myCMD = 'rm -f ' + UPLOAD_FOLDER + '/input.txt'
    os.system(myCMD)
    myCMD = 'cp ' + filename + ' ' + UPLOAD_FOLDER + '/input.txt'
    os.system(myCMD)
    
    myCMD = 'mpirun -np 8 -host master,client ' + UPLOAD_FOLDER + '/tsp' #ta będzie docelowo
    out = UPLOAD_FOLDER + '/out.txt'
    cmd = myCMD + ' > ' + out
    os.system(cmd)

    f = open(out, "r")
    contents = f.read()
    f.close()

    lista = contents.split('\n')

    lista3 = lista[0]
    for miasto in lista[1:-2]:
        lista3 = lista3 + '-' + miasto
    
    task = Task.query.filter_by(id=task_id).first()
    setattr(task, "progress", 100)
    setattr(task, "tsp_path", str(lista3))
    setattr(task, "cost", int(lista[-2]))
    db.session.commit()
    print('Zapisano wynik', file=sys.stderr)
    pass

@app.route('/getHistory', methods=['POST'])
def get_history():
    #print('KOTY SA MILE', file=sys.stderr)
    print(request.form['user'], file=sys.stderr)
    user_task = Task.query.filter_by(user_id=request.form['user'])
    return json.dumps([i.serialize for i in user_task.all()])
    print(user_task.all())
    #return json.dumps(user_task.all())

@app.route('/user/register', methods=['POST'])
# @token_required
def create_user():
    data = request.get_json()

    hashed_password = generate_password_hash(data['password'], method='sha256')

    new_user = User(public_id=str(uuid.uuid4()), name=data['username'], password=hashed_password, admin=False)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({'message' : 'Stworzono użytkownika!', 'id': str(uuid.uuid4())})

@app.route('/login', methods=['POST'])
@cross_origin()
def login():
    data = request.get_json()

    user = User.query.filter_by(name=data['username']).first()

    if check_password_hash(user.password, data['password']):
        return jsonify({'message' : 'Zalogowano użytkownika', 'id': user.public_id})
    return make_response('Could not verify', 401, {'WWW-Authenticate' : 'Basic realm="Wymagany login"'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
