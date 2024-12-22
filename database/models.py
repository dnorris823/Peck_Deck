
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

import datetime

Base = declarative_base()


class Users(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    password = Column(String, nullable=False)

    # children
    devices = relationship('Devices', back_populates='users')
    device_users = relationship('DeviceUsers', back_populates='users')
    
class Devices(Base):
    __tablename__ = 'devices'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    city = Column(String, nullable=False)
    state = Column(String, nullable=False)
    owner = Column(Integer, ForeignKey('users.id'))
    
    # parent
    users = relationship('Users', back_populates='devices')
    
    # children
    device_users = relationship('DeviceUsers', back_populates='devices')
    sightings = relationship('Sightings', back_populates='devices')
    
class DeviceUsers(Base):
    __tablename__ = 'device_users'
    id = Column(Integer, primary_key=True)
    device_id = Column(Integer, ForeignKey('devices.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    
    # parent
    devices = relationship('Devices', back_populates='device_users')
    users = relationship('Users', back_populates='device_users')

class Species(Base):
    __tablename__ = 'species'
    id = Column(Integer, primary_key=True)
    common_name = Column(String, nullable=False)
    genus = Column(String, nullable=False)
    species = Column(String, nullable=False)
    order = Column(String, nullable=False)
    wiki_url = Column(String, nullable=False)

    # children
    sightings = relationship('Sightings', back_populates='species')

class Sightings(Base):
    __tablename__ = 'sightings'
    id = Column(Integer, primary_key=True)
    species_id= Column(Integer, ForeignKey('species.id'))
    device_id = Column(Integer, ForeignKey('devices.id'))
    datetime = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    photo_storage_location = Column(String)
    weather_conditions = Column(String)
    feed_type = Column(String)

    # parents
    species = relationship('Species', back_populates='sightings')
    devices = relationship('Devices', back_populates='sightings')

