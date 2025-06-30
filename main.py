import os
import discord
from discord.ext import commands
from dotenv import load_dotenv # Asegúrate de que esto todavía esté si usas .env localmente
import motor.motor_asyncio
import asyncio
from discord import app_commands

load_dotenv()

# TOKEN del bot
# CAMBIO AQUÍ: Usar DISCORD_BOT_TOKEN en lugar de DISCORD_TOKEN
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# CAMBIO AQUÍ: Usar MONGO_URI en lugar de MONGODB_URI
MONGODB_URI = os.getenv('MONGO_URI')

# Definir los intents necesarios
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Inicializar el bot
bot = commands.Bot(command_prefix='!', intents=intents)

# Variable global para la base de datos
bot.db = None

async def connect_to_mongodb():
    global bot
    try:
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
        bot.db = client.discord_academy # Nombre de tu base de datos
        print("Conectado a MongoDB Atlas con éxito.")
    except Exception as e:
        print(f"ERROR al conectar a MongoDB Atlas: {e}")
        bot.db = None

async def load_cogs():
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            try:
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f"Módulo cogs.{filename[:-3]} cargado correctamente.")
            except Exception as e:
                print(f"ERROR al cargar cogs.{filename[:-3]}: {e}")

@bot.event
async def on_ready():
    print(f'¡Bot conectado como {bot.user}!')
    print(f'ID del Bot: {bot.user.id}')
    
    await connect_to_mongodb()
    await load_cogs()

    try:
        synced_commands = await bot.tree.sync()
        print(f"Sincronizados {len(synced_commands)} comandos de barra.")
    except Exception as e:
        print(f"Error al sincronizar comandos de barra: {e}")

    print('-------------------------------------------')

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CommandInvokeError):
        original_error = error.original
        
        if isinstance(original_error, discord.errors.NotFound) and original_error.code == 10062:
            print(f"ADVERTENCIA: Interacción desconocida para el comando '{interaction.command.name}' de {interaction.user} en {interaction.guild}. (Posible timeout)")
            try:
                if not interaction.response.is_done():
                     await interaction.response.send_message("❌ Lo siento, la interacción con este comando expiró o no se encontró. Por favor, inténtalo de nuevo.", ephemeral=True)
                else:
                    if not interaction.response.is_sent():
                        await interaction.followup.send("❌ Lo siento, la interacción con este comando expiró o no se encontró. Por favor, inténtalo de nuevo.", ephemeral=True)
            except discord.errors.InteractionResponded:
                pass
            except Exception as e:
                print(f"Error al intentar enviar mensaje de error de timeout: {e}")
            return

        elif isinstance(original_error, discord.errors.Forbidden):
            print(f"ERROR de permisos para el comando '{interaction.command.name}' de {interaction.user} en {interaction.guild}: {original_error.text}")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"❌ ¡Parece que me faltan permisos! Necesito `{original_error.text.split('permissions')[-1].strip()}` para ejecutar este comando. Por favor, asegúrate de que mi rol esté configurado correctamente.", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ ¡Parece que me faltan permisos! Necesito `{original_error.text.split('permissions')[-1].strip()}` para ejecutar este comando. Por favor, asegúrate de que mi rol esté configurado correctamente.", ephemeral=True)
            except discord.errors.InteractionResponded:
                pass
            except Exception as e:
                print(f"Error al intentar enviar mensaje de error de Forbidden: {e}")
            return
        
        print(f"ERROR en comando de barra '{interaction.command.name}':", original_error)
        
    elif isinstance(error, app_commands.MissingPermissions):
        missing_perms = [perm.replace('_', ' ').title() for perm in error.missing_permissions]
        message = f"❌ No tienes los permisos necesarios para usar este comando. Te faltan los siguientes permisos: `{'`, `'.join(missing_perms)}`."
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)
        print(f"Usuario {interaction.user} intentó usar '{interaction.command.name}' sin permisos: {error.missing_permissions}")

    elif isinstance(error, app_commands.BotMissingPermissions):
        missing_perms = [perm.replace('_', ' ').title() for perm in error.missing_permissions]
        message = f"❌ Necesito permisos para ejecutar este comando. Me faltan los siguientes permisos: `{'`, `'.join(missing_perms)}`. Por favor, asegúrate de que mi rol tenga estos permisos y esté configurado correctamente."
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)
        print(f"Bot le faltan permisos para '{interaction.command.name}': {error.missing_permissions}")

    elif isinstance(error, app_commands.NoPrivateMessage):
        await interaction.response.send_message("❌ Este comando no se puede usar en mensajes directos.", ephemeral=True)
        print(f"Comando '{interaction.command.name}' usado en DM.")
        
    else:
        print(f"ERROR NO MANEJADO en comando de barra '{interaction.command.name}': {type(error).__name__}: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Ocurrió un error inesperado al ejecutar el comando: `{type(error).__name__}`.", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Ocurrió un error inesperado al ejecutar el comando: `{type(error).__name__}`.", ephemeral=True)


# Iniciar el bot
bot.run(TOKEN)