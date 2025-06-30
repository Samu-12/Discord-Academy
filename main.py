import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import motor.motor_asyncio # Importamos motor

# Cargar las variables de entorno
load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI") # Obtenemos la URI de MongoDB

# Definir los intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

# --- Conexión a MongoDB ---
bot.mongo_client = None
bot.db = None

async def connect_to_mongodb():
    """Conecta el bot a MongoDB Atlas."""
    try:
        bot.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        bot.db = bot.mongo_client.discord_bot_db # Nombre de tu base de datos
        print("Conectado a MongoDB Atlas con éxito.")
    except Exception as e:
        print(f"Error al conectar a MongoDB: {e}")
        # Considera una reconexión o un cierre elegante si la conexión es crítica
# --- Fin Conexión a MongoDB ---


@bot.event
async def on_ready():
    print(f'¡Bot conectado como {bot.user}!')
    print(f'ID del Bot: {bot.user.id}')
    await connect_to_mongodb() # Llamamos a la función de conexión cuando el bot esté listo
    print('-------------------------------------------')

@bot.command(name='ping')
async def ping(ctx):
    """Responde con 'Pong!' para verificar que el bot está activo."""
    await ctx.send('Pong!')

# Puedes añadir un comando de ejemplo para probar la DB (opcional por ahora)
@bot.command(name='test_db')
async def test_db(ctx):
    """Comando para probar la conexión a la base de datos."""
    if bot.db:
        try:
            # Intentamos insertar un documento simple en una colección de prueba
            test_collection = bot.db.test_collection
            await test_collection.insert_one({"message": "Hello from MongoDB!", "user_id": ctx.author.id})
            await ctx.send("¡Conexión a MongoDB exitosa y dato insertado!")
            # También podemos intentar encontrarlo
            data = await test_collection.find_one({"user_id": ctx.author.id})
            if data:
                await ctx.send(f"Dato recuperado: {data['message']}")
        except Exception as e:
            await ctx.send(f"Error al interactuar con MongoDB: {e}")
    else:
        await ctx.send("El bot no está conectado a MongoDB.")


if __name__ == "__main__":
    if DISCORD_BOT_TOKEN and MONGO_URI:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("Error: Asegúrate de tener DISCORD_BOT_TOKEN y MONGO_URI en tu archivo .env.")