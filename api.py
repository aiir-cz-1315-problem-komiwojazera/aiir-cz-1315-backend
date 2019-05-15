from flask import Flask, request, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin
import uuid
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
from functools import wraps
import subprocess
import sys
import os

app = Flask(__name__)
CORS(app)

app.config['SECRET_KEY'] = 'thisissecret'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://///home/lukasz/gitAiir/aiir-cz-1315-backend/todo.db'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(50), unique=True)
    name = db.Column(db.String(50))
    password = db.Column(db.String(80))
    admin = db.Column(db.Boolean)

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
def mpi():
    data = request.get_json()
    print(data)
    n = data['problem_name']
    print(n)
    myCMD = 'mpirun -n 2 /home/lukasz/MPITest 1 '
    out = ' > out.txt'
    cmd = myCMD + n + out
    os.system(cmd)
    print(cmd)
    f = open("out.txt","r")

    contents = f.read()
    print(contents)

    f.close()
    return jsonify({'result' : str(contents)})
'''def connect():
    HOST="lukasz@192.168.0.110"
    data = request.get_json()
    n = data['problem_name']
    COMMAND="mpirun -n 2 MPITest 0"
    command2 = COMMAND + n
    ssh = subprocess.Popen(["ssh", "%s" % HOST, command2],
                       shell=False,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    result = ssh.stdout.readlines()
    if result == []:
        error = ssh.stderr.readlines()
    #print >>sys.stderr, "ERROR: %s" % error
    else:
        print (result)
'''
@app.route('/user/register', methods=['POST'])
# @token_required
def create_user():
    data = request.get_json()

    hashed_password = generate_password_hash(data['password'], method='sha256')

    new_user = User(public_id=str(uuid.uuid4()), name=data['username'], password=hashed_password, admin=False)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({'message' : 'Stworzono użytkownika!'})

@app.route('/login', methods=['POST'])
@cross_origin()
def login():
    data = request.get_json()

    user = User.query.filter_by(name=data['username']).first()

    if check_password_hash(user.password, data['password']):
        return jsonify({'message' : 'Zalogowano użytkownika'})
    return make_response('Could not verify', 401, {'WWW-Authenticate' : 'Basic realm="Wymagany login"'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)




