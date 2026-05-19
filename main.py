from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import random
import string
import requests
import json

from jose import JWTError, jwt
from passlib.context import CryptContext

from database import engine, SessionLocal
from models import Base, User, Usuario, Pedido, Cliente, Conductor

# ==========================================
# CONFIG
# ==========================================
SECRET_KEY = "dM7#kP9$xQnL2@vRtW5!yBsE8^jFhN3&uCgA6*mZoKp4JiYeXd"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480

GOOGLE_API_KEY = "AIzaSyDS1-kPw16T5zdnj3FVQK_km1btwcJWln4"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ==========================================
# UTF8 JSON RESPONSE
# ==========================================
class UTF8JSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")

app = FastAPI(
    title="API DeliverMaps",
    default_response_class=UTF8JSONResponse
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

# ==========================================
# DB DEPENDENCY
# ==========================================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# JWT HELPERS
# ==========================================
def crear_token_panel(data: dict) -> str:
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload["exp"] = expire
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def crear_token_flutter(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

# ==========================================
# AUTH DEPENDENCIES
# ==========================================

# Para el panel Vue — usa HTTPBearer y sub como string
def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Token inválido")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or user.rol != "admin":
        raise HTTPException(status_code=403, detail="Acceso solo para administradores")
    return user

# Para Flutter — usa OAuth2 y user_id como int
def obtener_usuario_actual(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    usuario = db.query(User).filter(User.id == user_id).first()
    if usuario is None:
        raise credentials_exception
    return usuario

# ==========================================
# SCHEMAS PYDANTIC
# ==========================================
class LoginRequest(BaseModel):
    email: str
    password: str

class RegistroRequest(BaseModel):
    nombre: str
    email: str
    password: str
    rol: str
    latitud_inicial: Optional[float] = 10.39972
    longitud_inicial: Optional[float] = -75.51444

class PedidoCreate(BaseModel):
    cedula: str
    nombre: str
    telefono: str
    barrio: str
    direccion: str
    comp_dir: Optional[str] = None

class PedidoUpdate(BaseModel):
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    barrio: Optional[str] = None
    direccion: Optional[str] = None
    comp_dir: Optional[str] = None
    estado: Optional[str] = None

# ==========================================
# HELPERS
# ==========================================
def obtener_coordenadas(direccion: str):
    try:
        direccion_completa = f"{direccion}, Cartagena, Colombia"
        response = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": direccion_completa, "key": GOOGLE_API_KEY}
        )
        data = response.json()
        print("GEOCODING RESPONSE:", data)
        if data["status"] == "OK":
            location = data["results"][0]["geometry"]["location"]
            return {"lat": location["lat"], "lng": location["lng"]}
    except Exception as e:
        print("ERROR GEOCODING:", e)
    return None

def generar_guia(db: Session) -> str:
    while True:
        letras = ''.join(random.choices(string.ascii_uppercase, k=3))
        numeros = ''.join(random.choices(string.digits, k=6))
        guia = f"{letras}{numeros}"
        existe = db.query(Pedido).filter(Pedido.numero_pedido == guia).first()
        if not existe:
            return guia

def asignar_conductor(db: Session) -> int:
    conteo = (
        db.query(
            Pedido.id_conductor,
            func.count(Pedido.id).label("activos")
        )
        .filter(Pedido.estado.notin_(["entregado", "cancelado"]))
        .group_by(Pedido.id_conductor)
        .subquery()
    )
    resultado = (
        db.query(User.id, func.coalesce(conteo.c.activos, 0).label("activos"))
        .outerjoin(conteo, User.id == conteo.c.id_conductor)
        .filter(User.rol == "conductor")
        .order_by("activos")
        .first()
    )
    if not resultado:
        raise HTTPException(
            status_code=400,
            detail="No hay conductores registrados en el sistema."
        )
    return resultado[0]

# ==========================================
# RUTAS PÚBLICAS
# ==========================================
@app.get("/")
def root():
    return {"message": "API DeliverMaps funcionando"}

# ── LOGIN PANEL (Vue) ─────────────────────
@app.post("/api/login")
def login_panel(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

    # Intenta verificar con bcrypt primero, luego texto plano
    password_valido = False
    try:
        password_valido = pwd_context.verify(data.password, user.password)
    except Exception:
        password_valido = (data.password == user.password)

    if not password_valido:
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos")

    if user.rol != "admin":
        raise HTTPException(status_code=403, detail="Acceso solo para administradores")

    token = crear_token_panel({"sub": str(user.id), "rol": user.rol})

    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": {
            "id": user.id,
            "nombre": user.nombre,
            "email": user.email,
            "rol": user.rol,
        }
    }

# ── LOGIN FLUTTER ─────────────────────────
@app.post("/login")
def login_flutter(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    # Intenta verificar con bcrypt primero, luego texto plano
    password_valido = False
    try:
        password_valido = pwd_context.verify(data.password, user.password)
    except Exception:
        password_valido = (data.password == user.password)

    if not password_valido:
        raise HTTPException(status_code=401, detail="Credenciales incorrectas")

    access_token = crear_token_flutter({"user_id": user.id})

    return {
        "message": "Login exitoso",
        "access_token": access_token,
        "token_type": "bearer",
        "id": user.id,
        "email": user.email,
        "nombre": user.nombre,
        "rol": user.rol
    }

# ── RASTREO PÚBLICO ───────────────────────
@app.get("/api/pedidos/rastreo/{busqueda}")
def consultar_pedido(busqueda: str, db: Session = Depends(get_db)):
    pedido = db.query(Pedido).join(Cliente).filter(
        (Pedido.numero_pedido == busqueda.upper()) |
        (Cliente.cedula == busqueda)
    ).first()

    if not pedido:
        raise HTTPException(status_code=404, detail="No encontramos ningún pedido.")

    cliente = db.query(Cliente).filter(Cliente.id_cliente == pedido.id_cliente).first()

    return {
        "numero_pedido": pedido.numero_pedido,
        "cliente": cliente.nombre if cliente else "Desconocido",
        "estado": pedido.estado,
        "fecha": pedido.fecha,
    }

# ==========================================
# RUTAS PANEL VUE (/api/)
# ==========================================

# ── Usuarios ──────────────────────────────
@app.post("/api/usuarios", status_code=201)
def register_panel(
    data: RegistroRequest,
    db: Session = Depends(get_db),
):
    if data.rol not in ("admin", "conductor"):
        raise HTTPException(status_code=400, detail="Rol inválido.")

    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="El correo ya está en uso.")

    hashed = pwd_context.hash(data.password)

    nuevo_user = User(
        nombre=data.nombre,
        email=data.email,
        password=hashed,
        rol=data.rol.lower(),
    )
    db.add(nuevo_user)
    db.commit()
    db.refresh(nuevo_user)

    if nuevo_user.rol == "conductor":
        nuevo_conductor = Conductor(
            id_conductor=nuevo_user.id,
            ultima_latitud=data.latitud_inicial,
            ultima_longitud=data.longitud_inicial
        )
        db.add(nuevo_conductor)
        db.commit()

    return {"message": f"{data.rol.capitalize()} registrado exitosamente."}

@app.get("/api/usuarios")
def obtener_usuarios(db: Session = Depends(get_db)):
    usuarios = db.query(User).all()
    return [{"id": u.id, "nombre": u.nombre, "email": u.email, "rol": u.rol} for u in usuarios]

@app.delete("/api/usuarios/{id_usuario}")
def borrar_usuario(id_usuario: int, db: Session = Depends(get_db)):
    usuario = db.query(User).filter(User.id == id_usuario).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    db.delete(usuario)
    db.commit()
    return {"message": "Usuario eliminado exitosamente."}

# ── Pedidos Panel ─────────────────────────
@app.get("/api/pedidos")
def obtener_pedidos_panel(db: Session = Depends(get_db)):
    pedidos = db.query(Pedido).order_by(Pedido.fecha.desc()).all()
    resultado = []
    for p in pedidos:
        cliente = db.query(Cliente).filter(Cliente.id_cliente == p.id_cliente).first()
        resultado.append({
            "id": p.id,
            "numero_pedido": p.numero_pedido,
            "id_cliente": cliente.cedula if cliente else None,
            "nombre_cliente": cliente.nombre if cliente else None,
            "telefono_cliente": cliente.telefono if cliente else None,
            "barrio": p.barrio,
            "direccion": p.direccion,
            "comp_dir": p.comp_dir,
            "estado": p.estado,
            "id_conductor": p.id_conductor,
            "latitud_destino": float(p.latitud_destino) if p.latitud_destino else None,
            "longitud_destino": float(p.longitud_destino) if p.longitud_destino else None,
        })
    return resultado

@app.post("/api/pedidos", status_code=201)
def crear_pedido_panel(
    data: PedidoCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    try:
        cliente = db.query(Cliente).filter(Cliente.cedula == data.cedula).first()
        if not cliente:
            cliente = Cliente(cedula=data.cedula, nombre=data.nombre, telefono=data.telefono)
            db.add(cliente)
            db.commit()
            db.refresh(cliente)

        id_conductor_asignado = asignar_conductor(db)

        # Obtener coordenadas con Google
        coordenadas = obtener_coordenadas(data.direccion)

        nuevo_pedido = Pedido(
            numero_pedido=generar_guia(db),
            id_cliente=cliente.id_cliente,
            barrio=data.barrio,
            direccion=data.direccion,
            comp_dir=data.comp_dir,
            estado="pendiente",
            id_conductor=id_conductor_asignado,
            user_id=admin.id,
            latitud_destino=coordenadas["lat"] if coordenadas else None,
            longitud_destino=coordenadas["lng"] if coordenadas else None,
        )

        db.add(nuevo_pedido)
        db.commit()
        db.refresh(nuevo_pedido)

        return {"message": "Pedido creado", "numero_pedido": nuevo_pedido.numero_pedido}

    except Exception as e:
        db.rollback()
        print(f"ERROR AL CREAR PEDIDO: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Fallo en BD: {str(e)}")

@app.put("/api/pedidos/{id_pedido}")
def actualizar_pedido(
    id_pedido: int,
    data: PedidoUpdate,
    db: Session = Depends(get_db),
):
    pedido = db.query(Pedido).filter(Pedido.id == id_pedido).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")

    ESTADOS_VALIDOS = {"pendiente", "en_camino", "en_reparto", "entregado", "cancelado"}

    if data.estado is not None:
        if data.estado not in ESTADOS_VALIDOS:
            raise HTTPException(status_code=400, detail=f"Estado inválido '{data.estado}'.")
        pedido.estado = data.estado

    if data.barrio is not None and data.barrio.strip():
        pedido.barrio = data.barrio.strip()
    if data.direccion is not None and data.direccion.strip():
        pedido.direccion = data.direccion.strip()
    if data.comp_dir is not None:
        pedido.comp_dir = data.comp_dir.strip() or None

    cliente = db.query(Cliente).filter(Cliente.id_cliente == pedido.id_cliente).first()
    if cliente:
        if data.nombre is not None and data.nombre.strip():
            cliente.nombre = data.nombre.strip()
        if data.telefono is not None and data.telefono.strip():
            cliente.telefono = data.telefono.strip()

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar cambios: {str(e)}")

    return {"message": "Pedido actualizado correctamente"}

@app.delete("/api/pedidos/{id_pedido}")
def borrar_pedido(id_pedido: int, db: Session = Depends(get_db)):
    pedido = db.query(Pedido).filter(Pedido.id == id_pedido).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado.")
    db.delete(pedido)
    db.commit()
    return {"message": "Eliminado exitosamente."}

# ==========================================
# RUTAS FLUTTER
# ==========================================

# ── Pedidos Flutter ───────────────────────
@app.get("/mis-pedidos")
def get_pedidos(
    usuario_actual: User = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db)
):
    pedidos = db.query(Pedido).filter(
        Pedido.id_conductor == usuario_actual.id,
        Pedido.estado != 'entregado'
    ).all()

    resultado = []
    for p in pedidos:
        resultado.append({
            "id": p.id,
            "numero": p.numero_pedido,
            "barrio": p.barrio,
            "direccion": p.direccion,
            "comp_dir": p.comp_dir,
            "estado": p.estado,
            "latitud_destino": float(p.latitud_destino) if p.latitud_destino else None,
            "longitud_destino": float(p.longitud_destino) if p.longitud_destino else None,
        })

    return resultado

@app.put("/entregar-pedido/{pedido_id}")
def entregar_pedido(
    pedido_id: int,
    usuario_actual: User = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db)
):
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if pedido.id_conductor != usuario_actual.id:
        raise HTTPException(status_code=403, detail="No autorizado")
    pedido.estado = 'entregado'
    db.commit()
    return {"message": "Pedido entregado correctamente"}

@app.get("/historial-pedidos")
def get_historial(
    usuario_actual: User = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db)
):
    pedidos = db.query(Pedido).filter(
        Pedido.id_conductor == usuario_actual.id,
        Pedido.estado == 'entregado'
    ).order_by(Pedido.fecha.desc()).all()

    return [
        {
            "id": p.id,
            "numero": p.numero_pedido,
            "barrio": p.barrio,
            "direccion": p.direccion,
            "estado": p.estado,
            "fecha": p.fecha.strftime("%d/%m/%Y %H:%M") if p.fecha else "Sin fecha",
        }
        for p in pedidos
    ]

@app.get("/estadisticas")
def get_estadisticas(
    usuario_actual: User = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db)
):
    total_entregados = db.query(Pedido).filter(
        Pedido.id_conductor == usuario_actual.id,
        Pedido.estado == 'entregado'
    ).count()

    total_pendientes = db.query(Pedido).filter(
        Pedido.id_conductor == usuario_actual.id,
        Pedido.estado == 'pendiente'
    ).count()

    total_pedidos = db.query(Pedido).filter(
        Pedido.id_conductor == usuario_actual.id
    ).count()

    dias = db.query(
        func.count(Pedido.id).label("total"),
        func.date(Pedido.fecha).label("dia")
    ).filter(
        Pedido.id_conductor == usuario_actual.id,
        Pedido.estado == 'entregado'
    ).group_by(func.date(Pedido.fecha)).all()

    promedio_por_dia = round(
        sum(d.total for d in dias) / len(dias), 1
    ) if dias else 0

    barrio_top = db.query(
        Pedido.barrio,
        func.count(Pedido.id).label("total")
    ).filter(
        Pedido.id_conductor == usuario_actual.id,
        Pedido.estado == 'entregado'
    ).group_by(Pedido.barrio).order_by(
        func.count(Pedido.id).desc()
    ).first()

    return {
        "total_pedidos": total_pedidos,
        "total_entregados": total_entregados,
        "total_pendientes": total_pendientes,
        "promedio_por_dia": promedio_por_dia,
        "barrio_top": barrio_top.barrio if barrio_top else "Sin datos",
        "barrio_top_cantidad": barrio_top.total if barrio_top else 0,
    }

@app.put("/iniciar-todos-pedidos")
def iniciar_todos_pedidos(
    usuario_actual: User = Depends(obtener_usuario_actual),
    db: Session = Depends(get_db)
):
    pedidos = db.query(Pedido).filter(
        Pedido.id_conductor == usuario_actual.id,
        Pedido.estado == 'pendiente'
    ).all()

    for pedido in pedidos:
        pedido.estado = 'en_camino'

    db.commit()
    return {"message": f"{len(pedidos)} pedidos actualizados a en_camino"}
