from sqlalchemy import (
    Column, Integer, String, ForeignKey,
    Float, Boolean, Text, Enum, DateTime,
    DECIMAL, TIMESTAMP
)
from sqlalchemy.sql import func
from database import Base


# =========================
# USUARIOS
# =========================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    password = Column(String(255), nullable=False)
    rol = Column(Enum('cliente', 'conductor', 'admin'), nullable=False)

# Alias para compatibilidad con el panel
Usuario = User


# =========================
# CONDUCTORES
# =========================
class Conductor(Base):
    __tablename__ = "conductor"

    id_conductor = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )
    ultima_latitud = Column(DECIMAL(10, 8), nullable=True)
    ultima_longitud = Column(DECIMAL(11, 8), nullable=True)
    disponible = Column(Boolean, default=True)


# =========================
# CLIENTES
# =========================
class Cliente(Base):
    __tablename__ = "clientes"

    id_cliente = Column(Integer, primary_key=True, index=True)
    cedula = Column(String(20), unique=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    telefono = Column(String(20))
    fecha_registro = Column(TIMESTAMP, server_default=func.now())


# =========================
# PEDIDOS
# =========================
class Pedido(Base):
    __tablename__ = "pedido"

    id = Column(Integer, primary_key=True, index=True)

    numero_pedido = Column(String(50), unique=True, nullable=False)

    id_cliente = Column(
        Integer,
        ForeignKey("clientes.id_cliente", ondelete="SET NULL"),
        nullable=True
    )

    barrio = Column(String(100), nullable=False)
    direccion = Column(Text)
    comp_dir = Column(String(200), nullable=True)

    latitud_destino = Column(Float, nullable=True)
    longitud_destino = Column(Float, nullable=True)

    estado = Column(
        Enum('pendiente', 'en_camino','en_reparto', 'entregado', 'cancelado'),
        nullable=False
    )

    fecha = Column(TIMESTAMP, server_default=func.now())

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )

    id_conductor = Column(
        Integer,
        ForeignKey("conductor.id_conductor", ondelete="SET NULL"),
        nullable=True
    )