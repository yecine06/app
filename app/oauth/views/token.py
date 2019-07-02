from flask import request, jsonify

from app.extensions import db
from app.jose_utils import make_id_token
from app.log import LOG
from app.models import Client, AuthorizationCode, OauthToken, ClientUser
from app.oauth.base import oauth_bp
from app.oauth.views.authorize import generate_access_token
from app.oauth_models import ScopeE


@oauth_bp.route("/token", methods=["POST"])
def get_access_token():
    """
    Calls by client to exchange the access token given the authorization code.
    The client authentications using Basic Authentication.
    The form contains the following data:
    - grant_type: must be "authorization_code"
    - code: the code obtained in previous step
    """
    # Basic authentication
    oauth_client_id = (
        request.authorization and request.authorization.username
    ) or request.form.get("client_id")

    oauth_client_secret = (
        request.authorization and request.authorization.password
    ) or request.form.get("client_secret")

    client = Client.filter_by(
        oauth_client_id=oauth_client_id, oauth_client_secret=oauth_client_secret
    ).first()

    if not client:
        return jsonify(error="wrong client-id or client-secret"), 400

    # Get code from form data
    grant_type = request.form.get("grant_type")
    code = request.form.get("code")

    # sanity check
    if grant_type != "authorization_code":
        return jsonify(error="grant_type must be authorization_code"), 400

    auth_code: AuthorizationCode = AuthorizationCode.filter_by(code=code).first()
    if not auth_code:
        return jsonify(error=f"no such authorization code {code}"), 400

    if auth_code.client_id != client.id:
        return jsonify(error=f"are you sure this code belongs to you?"), 400

    LOG.debug(
        "Create Oauth token for user %s, client %s", auth_code.user, auth_code.client
    )

    # Create token
    oauth_token = OauthToken.create(
        client_id=auth_code.client_id,
        user_id=auth_code.user_id,
        scope=auth_code.scope,
        redirect_uri=auth_code.redirect_uri,
        access_token=generate_access_token(),
    )
    db.session.add(oauth_token)

    # Auth code can be used only once
    db.session.delete(auth_code)

    db.session.commit()

    client_user: ClientUser = ClientUser.get_by(
        client_id=auth_code.client_id, user_id=auth_code.user_id
    )

    user_data = client_user.get_user_info()

    res = {
        "access_token": oauth_token.access_token,
        "token_type": "bearer",
        "expires_in": 3600,
        "scope": "",
        "user": user_data,
    }

    if oauth_token.scope and ScopeE.OPENID.value in oauth_token.scope:
        res["id_token"] = make_id_token(client_user)

    return jsonify(res)