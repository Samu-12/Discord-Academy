import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import motor.motor_asyncio # Importamos motor

# Cargar las variables de entorno del archivo .env
load_dotenv()

# Obtener el token del bot y la URI de MongoDB desde las variables de entorno
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# Definir los intents necesarios para tu bot
# Es crucial habilitar los intents privilegiados en el portal de desarrolladores de Discord
intents = discord.Intents.default()
intents.members = True # Necesario para el conteo de miembros y bienvenidas
intents.message_content = True # Necesario para leer el contenido de los mensajes (moderación, reacciones, economía)
intents.presences = True # Necesario para el conteo de miembros (si quieres ver el estado de presencia)

# Crear una instancia del bot
# Puedes cambiar el prefijo de comando, por ejemplo, a '!' o '.'
bot = commands.Bot(command_prefix='!', intents=intents)

# --- Conexión a MongoDB ---
bot.mongo_client = None
bot.db = None

async def connect_to_mongodb():
    """Conecta el bot a MongoDB Atlas."""
    try:
        bot.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
        bot.db = bot.mongo_client.discord_bot_db # Nombre de tu base de datos (puedes cambiarlo si quieres)
        print("Conectado a MongoDB Atlas con éxito.")
    except Exception as e:
        print(f"Error al conectar a MongoDB: {e}")
        # Considera una reconexión o un cierre elegante si la conexión es crítica
# --- Fin Conexión a MongoDB ---

# Evento cuando el bot está listo y conectado
@bot.event
async def on_ready():
    print(f'¡Bot conectado como {bot.user}!')
    print(f'ID del Bot: {bot.user.id}')
    await connect_to_mongodb() # Llamamos a la función de conexión cuando el bot esté listo
    print('-------------------------------------------')

# Comando de ejemplo para probar que el bot funciona
@bot.command(name='ping')
async def ping(ctx):
    """Responde con 'Pong!' para verificar que el bot está activo."""
    await ctx.send('Pong!')

# Comando de ejemplo para probar la conexión a la base de datos
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

# --- Bienvenidas Personalizadas ---
@bot.event
async def on_member_join(member):
    """
    Gestiona el evento cuando un nuevo miembro se une al servidor.
    Envía un mensaje de bienvenida personalizado en el canal configurado.
    """
    if not bot.db: # Asegurarse de que la DB esté conectada
        print("Error: La base de datos no está conectada para el evento on_member_join.")
        return

    guild_id = member.guild.id
    # Intentar obtener la configuración de bienvenida para este servidor
    settings = await bot.db.welcome_settings.find_one({"_id": guild_id})

    welcome_channel_id = None
    if settings:
        welcome_channel_id = settings.get("channel_id")

    # Si no hay un canal configurado o el ID no es válido, no hacer nada
    if not welcome_channel_id:
        print(f"No hay un canal de bienvenida configurado para el servidor {member.guild.name}.")
        return

    welcome_channel = bot.get_channel(welcome_channel_id)

    if welcome_channel is None:
        print(f"El canal de bienvenida configurado ({welcome_channel_id}) no se encontró o no es accesible.")
        return

    # Contar miembros actuales
    member_count = len(member.guild.members) # Obtiene el número total de miembros

    # Crear el mensaje embed de bienvenida
    embed = discord.Embed(
        title=f"🎉 ¡Bienvenido a {member.guild.name}!",
        description=f"¡Hola {member.mention}! Nos alegra tenerte aquí.",
        color=0x7289DA # Un color agradable (Discord's Blurple)
    )
    # Establece el thumbnail con el avatar del usuario, o el avatar por defecto si no tiene uno
    embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
    embed.add_field(name="Miembros Actualmente", value=f"Somos **{member_count}** miembros en el servidor.", inline=False)
    embed.set_footer(text="¡Esperamos que disfrutes tu estancia!")
    # --- IMPORTANTE: CAMBIA ESTA URL por tu imagen personalizada! ---
    embed.set_image(url="https://cdn.discordapp.com/attachments/1386759618658697287/1389051793245339648/2c64af033af4ea637189.png?ex=686336ca&is=6861e54a&hm=f13285fb1eff12c71e896b76b5ffc677c84321fe78efc4b8c29c410da291d7f2&")

    try:
        await welcome_channel.send(embed=embed)
        print(f"Mensaje de bienvenida enviado para {member.name} en el servidor {member.guild.name}.")
    except discord.Forbidden:
        print(f"El bot no tiene permisos para enviar mensajes en el canal {welcome_channel.name} ({welcome_channel.id}) del servidor {member.guild.name}.")
    except Exception as e:
        print(f"Ocurrió un error al enviar el mensaje de bienvenida: {e}")


@bot.command(name='setbienvenida')
@commands.has_permissions(administrator=True) # Solo administradores pueden usar este comando
async def set_bienvenida(ctx, channel: discord.TextChannel):
    """
    Configura el canal de bienvenida para el servidor.
    Uso: !setbienvenida #nombre-del-canal
    """
    if not bot.db:
        await ctx.send("Error: La base de datos no está conectada. No se pudo configurar el canal.")
        return

    guild_id = ctx.guild.id
    channel_id = channel.id

    try:
        # Guardar o actualizar el ID del canal en la base de datos
        await bot.db.welcome_settings.update_one(
            {"_id": guild_id},
            {"$set": {"channel_id": channel_id}},
            upsert=True # Si no existe, lo inserta; si existe, lo actualiza
        )
        await ctx.send(f"✅ ¡El canal de bienvenida se ha configurado a {channel.mention} con éxito!")
        print(f"Canal de bienvenida configurado a {channel.name} ({channel.id}) para el servidor {ctx.guild.name}.")
    except Exception as e:
        await ctx.send(f"❌ Ocurrió un error al configurar el canal de bienvenida: {e}")
        print(f"Error al configurar el canal de bienvenida: {e}")

# --- Fin Bienvenidas Personalizadas ---


# Ejecutar el bot
if __name__ == "__main__":
    if DISCORD_BOT_TOKEN and MONGO_URI:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        print("Error: Asegúrate de tener DISCORD_BOT_TOKEN y MONGO_URI en tu archivo .env.")