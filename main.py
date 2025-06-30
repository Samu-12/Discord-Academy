import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import motor.motor_asyncio
import asyncio # Necesario para asyncio.sleep si se usa en algún cog o aquí

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

# Obtener los valores de las variables de entorno
# Asegúrate de que esta variable sea exactamente el nombre que usas en tu .env y Railway
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") 
MONGO_URI = os.getenv("MONGO_URI")

# --- Configuración de Intents de Discord ---
# Los Intents son permisos que tu bot necesita para recibir ciertos eventos de Discord.
# Es crucial habilitar los correctos tanto aquí como en el Portal de Desarrolladores de Discord.
intents = discord.Intents.default()
intents.members = True          # Necesario para el evento on_member_join (bienvenidas)
intents.message_content = True  # Necesario para que el bot pueda leer el contenido de los mensajes
                                # (esencial para comandos y moderación)
intents.presences = True        # Necesario para ver el estado de presencia de los miembros (opcional, pero útil)

# Inicializa el bot con un prefijo de comando y los intents configurados.
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Configuración de la Conexión a MongoDB ---
bot.mongo_client = None # Inicializa el cliente de MongoDB a None
bot.db = None           # Inicializa la base de datos a None

async def connect_to_mongodb():
    """
    Función asíncrona para establecer la conexión a MongoDB Atlas.
    """
    try:
        # Crea una instancia del cliente de MongoDB asíncrono
        bot.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        # Selecciona la base de datos que vas a usar (puedes cambiar 'discord_bot_db' por otro nombre si prefieres)
        bot.db = bot.mongo_client.discord_bot_db
        print("Conectado a MongoDB Atlas con éxito.")
    except Exception as e:
        print(f"Error al conectar a MongoDB: {e}")

# --- Función para cargar los cogs (módulos de funcionalidad) ---
async def load_cogs():
    """
    Carga todos los archivos .py dentro de la carpeta 'cogs' como extensiones del bot.
    """
    cogs_path = './cogs' # La ruta a la carpeta de cogs
    for filename in os.listdir(cogs_path):
        # Itera sobre los archivos en la carpeta 'cogs'
        if filename.endswith('.py') and filename != '__init__.py':
            # Si es un archivo Python y no es __init__.py, es un cog.
            # Construye el nombre del módulo: e.g., 'cogs.welcome', 'cogs.moderation'
            cog_name = f'cogs.{filename[:-3]}' # [:-3] para quitar la extensión '.py'
            try:
                # Carga la extensión (el cog) en el bot
                await bot.load_extension(cog_name)
                print(f'Módulo {cog_name} cargado correctamente.')
            except Exception as e:
                # Si hay un error al cargar un cog, lo imprime en la consola.
                print(f'Fallo al cargar el módulo {cog_name}: {e}')

# --- Evento: Cuando el Bot está Listo ---
@bot.event
async def on_ready():
    """
    Este evento se dispara una vez que el bot ha iniciado sesión y está listo.
    """
    print(f'¡Bot conectado como {bot.user}!')
    print(f'ID del Bot: {bot.user.id}')
    
    await connect_to_mongodb() # Conectar a MongoDB cuando el bot esté listo
    await load_cogs()          # Cargar todos los cogs después de conectar a la DB

    print('-------------------------------------------')

# --- Ejecutar el Bot ---
if __name__ == "__main__":
    # Verifica que las variables de entorno esenciales estén cargadas.
    if DISCORD_BOT_TOKEN and MONGO_URI:
        bot.run(DISCORD_BOT_TOKEN) # Inicia el bot con tu token de Discord
    else:
        # Mensaje de error si las variables no se encuentran (útil para depuración local)
        print("Error: Asegúrate de tener DISCORD_BOT_TOKEN y MONGO_URI en tu archivo .env.")