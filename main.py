import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import motor.motor_asyncio # Importamos motor, necesario para MongoDB

# Cargar las variables de entorno desde el archivo .env
# Esto permite que el bot lea tu DISCORD_BOT_TOKEN y MONGO_URI
load_dotenv()

# Obtener los valores de las variables de entorno
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# --- Configuración de Intents de Discord ---
# Los "Intents" le dicen a Discord qué eventos necesita ver tu bot.
# Son CRUCIALES. Si no los activas, ciertas funcionalidades no funcionarán.
# Es necesario activarlos también en el portal de desarrolladores de Discord.
intents = discord.Intents.default()
intents.members = True          # ¡IMPORTANTE para Bienvenidas y conteo de miembros!
intents.message_content = True  # ¡IMPORTANTE para comandos y leer mensajes!
intents.presences = True        # Necesario si quieres ver el estado de presencia de los usuarios (online, etc.)

# Crear una instancia del bot
# '!' será el prefijo para todos tus comandos (ej. !ping, !setbienvenida)
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Configuración de la Conexión a MongoDB ---
# Aquí es donde guardaremos la conexión a tu base de datos
bot.mongo_client = None # Guardará el cliente de conexión a MongoDB
bot.db = None           # Guardará la base de datos específica

async def connect_to_mongodb():
    """Función asíncrona para conectar el bot a MongoDB Atlas."""
    try:
        # Crea el cliente de MongoDB usando la URI de tu .env
        bot.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        # Selecciona la base de datos que usarás. Puedes llamarla como quieras, ej. "discord_bot_db"
        bot.db = bot.mongo_client.discord_bot_db
        print("Conectado a MongoDB Atlas con éxito.")
    except Exception as e:
        # Si hay un error al conectar, lo imprimimos
        print(f"Error al conectar a MongoDB: {e}")
        # En un bot real, quizás querrías hacer algo más sofisticado aquí (ej. reintentar)

# --- Evento: Cuando el Bot está Listo ---
@bot.event
async def on_ready():
    """Se ejecuta cuando el bot se ha conectado exitosamente a Discord."""
    print(f'¡Bot conectado como {bot.user}!') # Muestra el nombre del bot
    print(f'ID del Bot: {bot.user.id}')     # Muestra el ID único del bot
    await connect_to_mongodb()              # Intentamos conectar a MongoDB tan pronto como el bot esté listo
    print('-------------------------------------------')

# --- Comando de Prueba: !ping ---
@bot.command(name='ping')
async def ping(ctx):
    """Responde con 'Pong!' para verificar que el bot está activo y responde a comandos."""
    await ctx.send('Pong!')

# --- Comando de Prueba: !test_db (Opcional, pero útil para verificar DB) ---
@bot.command(name='test_db')
async def test_db(ctx):
    """Comando para probar que la conexión a la base de datos funciona y puedes guardar/recuperar datos."""
    # ¡CORRECCIÓN AQUÍ! Cambiado 'if bot.db:' a 'if bot.db is not None:'
    if bot.db is not None:
        try:
            # Selecciona una colección de prueba (ej. 'test_collection')
            test_collection = bot.db.test_collection
            # Inserta un documento simple
            await test_collection.insert_one({"message": "Hola desde MongoDB!", "user_id": ctx.author.id})
            await ctx.send("✅ ¡Conexión a MongoDB exitosa y dato insertado!")
            # Intenta recuperar el dato que acabas de insertar
            data = await test_collection.find_one({"user_id": ctx.author.id})
            if data:
                await ctx.send(f"Dato recuperado: {data['message']}")
        except Exception as e:
            await ctx.send(f"❌ Error al interactuar con MongoDB: {e}")
    else:
        await ctx.send("❌ El bot no está conectado a MongoDB.")

# --- Funcionalidad: Bienvenidas Personalizadas ---

@bot.event
async def on_member_join(member):
    """
    Este evento se activa cuando un nuevo miembro se une al servidor.
    Envía un mensaje de bienvenida personalizado en el canal configurado.
    """
    # ¡CORRECCIÓN AQUÍ! Cambiado 'if not bot.db:' a 'if bot.db is None:'
    if bot.db is None:
        print("Error: La base de datos no está conectada. No se puede procesar el evento de bienvenida.")
        return

    guild_id = member.guild.id # Obtenemos el ID del servidor donde se unió el usuario

    # Buscamos la configuración de bienvenida para este servidor en la base de datos.
    # La colección se llama 'welcome_settings' y el _id es el ID del servidor.
    settings = await bot.db.welcome_settings.find_one({"_id": guild_id})

    welcome_channel_id = None
    if settings:
        # Si se encontró la configuración, obtenemos el ID del canal de bienvenida.
        welcome_channel_id = settings.get("channel_id")

    # Si no se ha configurado un canal de bienvenida para este servidor, no hacemos nada.
    if not welcome_channel_id:
        print(f"No hay un canal de bienvenida configurado para el servidor '{member.guild.name}' ({guild_id}).")
        return

    # Obtenemos el objeto del canal de Discord usando su ID.
    welcome_channel = bot.get_channel(welcome_channel_id)

    # Si el canal no existe, no es accesible para el bot, o fue eliminado, lo reportamos.
    if welcome_channel is None:
        print(f"El canal de bienvenida configurado ({welcome_channel_id}) para el servidor '{member.guild.name}' no se encontró o el bot no tiene acceso.")
        return

    # Contamos el número total de miembros en el servidor
    member_count = len(member.guild.members)

    # --- Creación del Mensaje de Bienvenida (Embed) ---
    embed = discord.Embed(
        title=f"🎉 ¡Bienvenido a {member.guild.name}!", # Título del embed
        description=f"¡Hola {member.mention}! Nos alegra tenerte aquí.", # Descripción del embed (menciona al nuevo miembro)
        color=0x7289DA # Color lateral del embed (Discord's Blurple)
    )
    # Establece la imagen de perfil del usuario como thumbnail (pequeña imagen en la esquina)
    # Usa el avatar del usuario si lo tiene, si no, usa el avatar por defecto de Discord
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    # Añade un campo al embed para mostrar el conteo de miembros
    embed.add_field(name="Miembros Actualmente", value=f"Somos **{member_count}** miembros en el servidor.", inline=False)
    # Añade un pie de página al embed
    embed.set_footer(text="¡Esperamos que disfrutes tu estancia!")
    # --- ¡IMPORTANTE! Configura una imagen principal para tu embed de bienvenida ---
    # Sube una imagen a un servicio como Imgur o cualquier host de imágenes
    # y pega aquí la URL directa de la imagen (debe terminar en .png, .jpg, .gif, etc.)
    embed.set_image(url="https://i.pinimg.com/736x/dd/2b/53/dd2b53b2a205336246eab2813738d5f7.jpg") # <<-- ¡CAMBIA ESTA URL!

    # --- Envío del Mensaje de Bienvenida ---
    try:
        await welcome_channel.send(embed=embed) # Envía el mensaje embed al canal configurado
        print(f"Mensaje de bienvenida enviado para {member.name} en el servidor '{member.guild.name}'.")
    except discord.Forbidden:
        # Si el bot no tiene permisos para enviar mensajes en ese canal
        print(f"El bot no tiene permisos para enviar mensajes en el canal {welcome_channel.name} ({welcome_channel.id}) del servidor '{member.guild.name}'.")
    except Exception as e:
        # Captura cualquier otro error durante el envío
        print(f"Ocurrió un error al enviar el mensaje de bienvenida: {e}")


@bot.command(name='setbienvenida')
@commands.has_permissions(administrator=True) # Este decorador asegura que SOLO los administradores puedan usar este comando
async def set_bienvenida(ctx, channel: discord.TextChannel):
    """
    Comando para configurar el canal de bienvenida para el servidor.
    Uso: !setbienvenida #nombre-del-canal
    """
    # ¡CORRECCIÓN AQUÍ! Cambiado 'if not bot.db:' a 'if bot.db is None:'
    if bot.db is None:
        await ctx.send("❌ Error: La base de datos no está conectada. No se pudo configurar el canal.")
        return

    guild_id = ctx.guild.id # ID del servidor donde se ejecutó el comando
    channel_id = channel.id # ID del canal que el administrador especificó

    try:
        # Guardamos o actualizamos el ID del canal en la colección 'welcome_settings' de MongoDB.
        # "_id": guild_id asegura que cada servidor tenga su propia configuración.
        # "$set": {"channel_id": channel_id} actualiza el ID del canal.
        # upsert=True: Si no existe un documento para este guild_id, lo crea; si existe, lo actualiza.
        await bot.db.welcome_settings.update_one(
            {"_id": guild_id},
            {"$set": {"channel_id": channel_id}},
            upsert=True
        )
        await ctx.send(f"✅ ¡El canal de bienvenida se ha configurado a {channel.mention} con éxito!")
        print(f"Canal de bienvenida configurado a {channel.name} ({channel.id}) para el servidor '{ctx.guild.name}'.")
    except Exception as e:
        await ctx.send(f"❌ Ocurrió un error al configurar el canal de bienvenida: {e}")
        print(f"Error al configurar el canal de bienvenida: {e}")

# --- Fin Funcionalidad: Bienvenidas Personalizadas ---


# --- Ejecutar el Bot ---
# Esto asegura que el bot solo se ejecute si este script es el principal
if __name__ == "__main__":
    if DISCORD_BOT_TOKEN and MONGO_URI: # Aquí no se cambia porque DISCORD_BOT_TOKEN y MONGO_URI son strings y None evalúa a False
        bot.run(DISCORD_BOT_TOKEN) # Inicia el bot con tu token de Discord
    else:
        print("Error: Asegúrate de tener DISCORD_BOT_TOKEN y MONGO_URI en tu archivo .env.")

