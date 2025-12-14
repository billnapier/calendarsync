import os
import firebase_admin
from firebase_admin import credentials, firestore, auth
from flask import Flask, render_template, request, session, redirect, url_for, jsonify

# Initialize Firebase Admin SDK
# If GOOGLE_APPLICATION_CREDENTIALS is set (locally or on Cloud Run if explicitly set), it uses that.
# On Cloud Run, it uses the default service account automatically if no creds provided.
if not firebase_admin._apps:
    project_id = os.environ.get('FIREBASE_PROJECT_ID')
    if project_id:
        firebase_admin.initialize_app(options={'projectId': project_id})
    else:
        firebase_admin.initialize_app()

app = Flask(__name__)
# Set a secret key for session management. 
# In production, this should be a strong random value from env var.
app.secret_key = os.environ.get('SECRET_KEY', 'dev_key_for_testing_only')

@app.route('/')
def home():
    user = session.get('user')
    firebase_config = {
        'apiKey': os.environ.get('FIREBASE_API_KEY'),
        'authDomain': os.environ.get('FIREBASE_AUTH_DOMAIN'),
        'projectId': os.environ.get('FIREBASE_PROJECT_ID'),
        'storageBucket': os.environ.get('FIREBASE_STORAGE_BUCKET'),
        'messagingSenderId': os.environ.get('FIREBASE_MESSAGING_SENDER_ID'),
        'appId': os.environ.get('FIREBASE_APP_ID')
    }
    return render_template('index.html', user=user, firebase_config=firebase_config)

@app.route('/login', methods=['POST'])
def login():
    id_token = request.json.get('idToken')
    if not id_token:
        return jsonify({'error': 'Missing ID token'}), 400

    try:
        # Verify the ID token while checking if the token is revoked by default
        decoded_token = auth.verify_id_token(id_token, check_revoked=True)
        uid = decoded_token['uid']
        name = decoded_token.get('name')
        email = decoded_token.get('email')
        picture = decoded_token.get('picture')

        # Create or update user in Firestore
        db = firestore.client()
        user_ref = db.collection('users').document(uid)
        user_data = {
            'name': name,
            'email': email,
            'picture': picture,
            'last_login': firestore.SERVER_TIMESTAMP
        }
        user_ref.set(user_data, merge=True)

        # Set session
        session['user'] = {
            'uid': uid,
            'name': name,
            'email': email,
            'picture': picture
        }
        
        return jsonify({'success': True}), 200

    except auth.RevokedIdTokenError:
        return jsonify({'error': 'ID token revoked'}), 401
    except auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid ID token'}), 401
    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))

if __name__ == '__main__':
    # Cloud Run sets PORT environment variable, default to 8080
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=True, host='0.0.0.0', port=port)
