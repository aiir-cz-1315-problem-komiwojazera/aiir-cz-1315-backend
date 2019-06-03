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
q = Queue(connection=conn, name='waiting_tasks', is_async=False)

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

'''
#doprowadzić do działania, jeśli chcemy przechowywać wyniki w bazie
class Result(db.Model):
    __tablename__ = 'result'
    id = db.Column(db.Integer, primary_key=True)
    cost = db.Column(db.Integer)
    tsp_path = db.Column(db.String(2000)) #wypisane miasta w kolejnosci odwiedzania?
    # można dołożyć pole task, jeśli chcemy mieć relację w obie strony

class Task(db.Model):
    __tablename__ = 'task'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('User.id'))
    user = relationship("User")
    result = relationship("Result") 
    completed = db.Column(db.Boolean)
'''

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
    '''
    if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
    ''' 
    #print(file)
    if file :#and allowed_file(file.filename):
        if not "file_number" in session:
            session["file_number"]=0
        session['file_number'] += 1     #unikamy dubli - najlepiej z jakims hashem
        filename = secure_filename(file.filename)# + session['file_number']
        destination = "/".join([target, filename])
        file.save(destination)
    '''
    new_task = Task(user=current_user, completed=False)
    db.session.add(new_task)
    db.session.commit()
    '''
    job = q.enqueue_call(
            func=mpi, args=(destination,) #, new_task)
        )
    #q.enqueue_call(
     #       func=mpi, args=(destination,) #, new_task)
      #  )
    while job.result == None:
        time.sleep(1)
   # result = job.wait_result(timeout=360)
    #return jsonify({'result' : 'Rozpoczęto obliczenia'})
    lista = job.result.split('\n')
   # lista2 = lista[1:-3]
    lista3 = lista[0]
    for miasto in lista[1:-2]:
        lista3 = lista3 + '-' + miasto
    #return jsonify({'result' : lista3})
    return jsonify({'result' : str(lista[-2]), 'route' : str(lista3)})

def mpi(filename):#, task):
    #można to bardziej elegancko zrobić, pobierajac w mpi filename jako argument
    #chyba że to koliduje z czymś jeszcze
    myCMD = 'rm -f ' + UPLOAD_FOLDER + '/input.txt'
    os.system(myCMD)
    myCMD = 'cp ' + filename + ' ' + UPLOAD_FOLDER + '/input.txt'
    os.system(myCMD)
    myCMD = 'mpirun -np 8 -host master,client ' + UPLOAD_FOLDER + '/tsp' #ta będzie docelowo
    
    '''out = ' > /home/metron/aiir-cz-1315-backend/out.txt'
    cmd = myCMD + out
    os.system(cmd)
    f = open("/home/metron/aiir-cz-1315-backend/out.txt","r")
    contents = f.read()
    print(contents, file=sys.stdout)

    new_result = Result(cost=-1, tsp_path='brak danych')
    task.completed = True
    result.tsp_path = contents
    task.result = new_result
    db.session.commit()
 
    #pass
    return jsonify({'result' : str(contents)}) '''
    '''out = ' > /home/lukasz/gitAiirTest/aiir-cz-1315-backend/out.txt'
    cmd = myCMD + out
    os.system(cmd)
    f = open("/home/lukasz/gitAiirTest/aiir-cz-1315-backend/out.txt","r")
    contents = f.read()
    f.close()
    return contents       
    pass'''
    out = UPLOAD_FOLDER + '/out.txt'
    cmd = myCMD + ' > ' + out
    os.system(cmd)
    f = open(out, "r")

    contents = f.read()
    #print(contents, file=sys.stdout)
    #cmd = 'echo ' + contents
    #os.system(cmd)
    f.close()
    #return jsonify({'result' : str(contents)})
    #time.sleep(10)
    return contents       
    pass

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
