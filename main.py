import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import motor.motor_asyncio
import asyncio
from discord import app_commands # Asegúrate de que esto esté importado

load_dotenv()

# TOKEN del bot (asegúrate de que esta variable de entorno exista en Railway/tu entorno)
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
# URI de MongoDB (asegúrate de que esta variable de entorno exista en Railway/tu entorno)
MONGODB_URI = os.getenv('MONGO_URI')

# Definir los intents necesarios
# Asegúrate de habilitar estos intents en el Portal de Desarrolladores de Discord para tu bot
intents = discord.Intents.default()
intents.members = True          # Necesario para acceder a miembros del gremio (roles, etc.)
intents.message_content = True  # Necesario si tu bot lee el contenido de mensajes (ej. para prefijos de comandos)
intents.guilds = True           # Necesario para gestionar guild_channels, roles, etc.

# Clase personalizada para el bot
class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!',  # Puedes cambiar este prefijo si lo deseas
            intents=intents,
            application_id=1258671607590897675 # Tu ID de aplicación de Discord
        )
        self.db = None # Se inicializará con la conexión a MongoDB en setup_hook

        # Mover el manejador de errores de comandos de barra dentro de la clase
        # Esto asegura que 'self.tree' ya está disponible cuando se define el manejador
        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.CommandInvokeError):
                original_error = error.original
                
                # Manejo de error por interacción desconocida (timeout o ya respondida)
                if isinstance(original_error, discord.errors.NotFound) and original_error.code == 10062:
                    print(f"ADVERTENCIA: Interacción desconocida para el comando '{interaction.command.name}' de {interaction.user} en {interaction.guild}. (Posible timeout)")
                    try:
                        if not interaction.response.is_done():
                            await interaction.response.send_message("❌ Lo siento, la interacción con este comando expiró o no se encontró. Por favor, inténtalo de nuevo.", ephemeral=True)
                        else:
                            if not interaction.response.is_sent():
                                await interaction.followup.send("❌ Lo siento, la interacción con este comando expiró o no se encontró. Por favor, inténtalo de nuevo.", ephemeral=True)
                    except discord.errors.InteractionResponded:
                        pass # Ya se había respondido, no hacer nada
                    except Exception as e:
                        print(f"Error al intentar enviar mensaje de error de timeout: {e}")
                    return

                # Manejo de error por permisos del bot faltantes (discord.Forbidden)
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
                
                # Otros errores de invocación de comandos
                print(f"ERROR en comando de barra '{interaction.command.name}':", original_error)
            
            # Manejo de errores por permisos de usuario faltantes
            elif isinstance(error, app_commands.MissingPermissions):
                missing_perms = [perm.replace('_', ' ').title() for perm in error.missing_permissions]
                message = f"❌ No tienes los permisos necesarios para usar este comando. Te faltan los siguientes permisos: `{'`, `'.join(missing_perms)}`."
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    await interaction.followup.send(message, ephemeral=True)
                print(f"Usuario {interaction.user} intentó usar '{interaction.command.name}' sin permisos: {error.missing_permissions}")

            # Manejo de errores por permisos de bot faltantes (app_commands.BotMissingPermissions)
            elif isinstance(error, app_commands.BotMissingPermissions):
                missing_perms = [perm.replace('_', ' ').title() for perm in error.missing_permissions]
                message = f"❌ Necesito permisos para ejecutar este comando. Me faltan los siguientes permisos: `{'`, `'.join(missing_perms)}`. Por favor, asegúrate de que mi rol tenga estos permisos y esté configurado correctamente."
                if not interaction.response.is_done():
                    await interaction.response.send_message(message, ephemeral=True)
                else:
                    await interaction.followup.send(message, ephemeral=True)
                print(f"Bot le faltan permisos para '{interaction.command.name}': {error.missing_permissions}")

            # Manejo de error si el comando no se puede usar en mensajes directos
            elif isinstance(error, app_commands.NoPrivateMessage):
                await interaction.response.send_message("❌ Este comando no se puede usar en mensajes directos.", ephemeral=True)
                print(f"Comando '{interaction.command.name}' usado en DM.")
                
            # Otros errores no manejados específicamente
            else:
                print(f"ERROR NO MANEJADO en comando de barra '{interaction.command.name}': {type(error).__name__}: {error}")
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Ocurrió un error inesperado al ejecutar el comando: `{type(error).__name__}`.", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Ocurrió un error inesperado al ejecutar el comando: `{type(error).__name__}`.", ephemeral=True)


    async def setup_hook(self):
        """
        Este método se ejecuta ANTES de on_ready, una vez que el bot
        está listo para procesar eventos, pero antes de que los sockets estén conectados.
        Es el lugar ideal para cargar cogs y sincronizar comandos de barra.
        """
        # 1. Conectar a MongoDB
        try:
            if MONGODB_URI:
                client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
                self.db = client.discord_academy # Asegúrate de que 'discord_academy' es el nombre correcto de tu base de datos
                print("Conectado a MongoDB Atlas con éxito en setup_hook.")
            else:
                print("MONGO_URI no configurada en las variables de entorno.")
        except Exception as e:
            print(f"ERROR al conectar a MongoDB Atlas en setup_hook: {e}")
            self.db = None # Asegúrate de que db es None si la conexión falla

        # 2. Cargar los cogs (los comandos de barra se registran aquí)
        # Asegúrate de que la carpeta 'cogs' exista y contenga tus archivos .py
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"Módulo cogs.{filename[:-3]} cargado correctamente.")
                except Exception as e:
                    print(f"ERROR al cargar cogs.{filename[:-3]}: {e}")

        # 3. Sincronizar comandos de barra con Discord
        # Esto envía la lista de todos los comandos registrados a Discord.
        # Puede tardar hasta 1 hora en propagarse globalmente.
        # Para pruebas rápidas en un servidor específico, puedes usar:
        # await self.tree.sync(guild=discord.Object(id=YOUR_GUILD_ID))
        # Reemplaza YOUR_GUILD_ID con el ID de tu servidor de Discord.
        try:
            synced_commands = await self.tree.sync() 
            print(f"Sincronizados {len(synced_commands)} comandos de barra.")
        except Exception as e:
            print(f"Error al sincronizar comandos de barra: {e}")

    async def on_ready(self):
        """
        on_ready se ejecuta cuando el bot se conecta completamente a Discord.
        En este punto, los cogs ya están cargados y los comandos sincronizados.
        """
        print(f'¡Bot conectado como {self.user}!')
        print(f'ID del Bot: {self.user.id}')
        print('-------------------------------------------')

# Iniciar la instancia del bot y correrlo
bot = MyBot() 
bot.run(TOKEN)