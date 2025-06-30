import discord
from discord.ext import commands
import re          # Para expresiones regulares (útil en anti-links y palabras)
import time        # Para el anti-spam basado en tiempo
import asyncio     # Necesario para asyncio.sleep en la función de mute temporal

# --- Constantes y Diccionarios Globales para el Cog (Temporales en Memoria) ---
# Estos diccionarios almacenan datos en tiempo real para la detección de spam.
# Se reiniciarán si el bot se reinicia.
# {guild_id: {user_id: [timestamp1, timestamp2, ...]}} - Para spam por frecuencia
spam_detection = {}
# {guild_id: {user_id: {"last_message_content": "text", "last_message_count": N}}} - Para spam por repetición
recent_messages = {}

# Constantes de configuración para la moderación (puedes ajustar estos valores)
SPAM_THRESHOLD_TIME = 5       # Tiempo en segundos: Si un usuario envía X mensajes en este tiempo, es spam.
SPAM_THRESHOLD_COUNT = 5      # Cantidad de mensajes: Si un usuario envía esta cantidad de mensajes...
SPAM_REPETITION_THRESHOLD = 3 # Cuántas veces un mensaje idéntico es considerado spam.

MAX_WARNINGS_BEFORE_MUTE = 3  # Cuántas advertencias un usuario puede recibir antes de ser muteado automáticamente.
MUTE_DURATION_SECONDS = 600   # Duración del mute en segundos (10 minutos de ejemplo).

# --- Clase Cog para Moderación ---
class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot # Almacena la instancia del bot para acceder a bot.db, etc.

    # --- Funciones Auxiliares para la Moderación ---

    async def get_moderation_settings(self, guild_id):
        """
        Obtiene la configuración de moderación (palabras prohibidas, enlaces permitidos, canal de logs)
        desde la base de datos para un servidor específico.
        Si no hay configuración, devuelve valores por defecto.
        """
        if self.bot.db is None:
            print("Error: La base de datos no está conectada para obtener configuración de moderación.")
            return {} # Devuelve un diccionario vacío si la DB no está disponible

        settings = await self.bot.db.moderation_settings.find_one({"_id": guild_id})
        if settings:
            return settings
        # Si no hay configuración en la DB, devuelve un diccionario con valores por defecto
        return {
            "prohibited_words": [],
            "allowed_links": [],
            "log_channel_id": None
        }

    async def send_mod_log(self, log_channel, embed_title, description, offender, action_type, reason, color, message_link=None):
        """
        Envía un mensaje embed al canal de logs de moderación del staff.
        """
        if log_channel:
            log_embed = discord.Embed(
                title=embed_title,
                description=description,
                color=color
            )
            log_embed.add_field(name="Usuario", value=offender.mention, inline=True)
            log_embed.add_field(name="ID de Usuario", value=offender.id, inline=True)
            log_embed.add_field(name="Acción", value=action_type, inline=True)
            log_embed.add_field(name="Razón", value=reason, inline=True)
            log_embed.set_footer(text=f"En canal: #{log_channel.name}")
            log_embed.timestamp = discord.utils.utcnow() # Marca de tiempo UTC

            if message_link:
                log_embed.add_field(name="Mensaje", value=f"[Ir al Mensaje]({message_link})", inline=False)

            try:
                await log_channel.send(embed=log_embed)
            except discord.Forbidden:
                print(f"ERROR: El bot no tiene permisos para enviar logs en el canal {log_channel.name} ({log_channel.id}).")
            except Exception as e:
                print(f"ERROR al enviar log de moderación: {e}")
        else:
            # Si no hay canal de logs configurado, imprime en la consola.
            print(f"MOD_LOG: {action_type} - {offender.name} | Razón: {reason}")


    async def warn_or_mute_user(self, member, reason, message_to_delete=None):
        """
        Maneja el sistema de advertencias y muteo automático para un usuario.
        """
        user_id = member.id
        guild_id = member.guild.id

        # Obtener las advertencias actuales del usuario desde la DB (colección 'user_moderation_data')
        # Utilizamos "_id": f"{guild_id}-{user_id}" como clave única para cada usuario por servidor
        user_data = await self.bot.db.user_moderation_data.find_one({"_id": f"{guild_id}-{user_id}"})
        current_warnings = user_data.get("warnings", 0) if user_data else 0

        current_warnings += 1 # Incrementamos la advertencia

        # Actualizar las advertencias en la DB
        await self.bot.db.user_moderation_data.update_one(
            {"_id": f"{guild_id}-{user_id}"},
            {"$set": {"warnings": current_warnings, "last_warn_timestamp": discord.utils.utcnow()}},
            upsert=True # Crea el documento si no existe
        )

        # Si el mensaje infractor existe, intentamos borrarlo
        if message_to_delete:
            try:
                await message_to_delete.delete()
            except discord.Forbidden:
                print(f"ERROR: No tengo permisos para eliminar el mensaje en {message_to_delete.channel.name} por {member.name}.")
            except Exception as e:
                print(f"ERROR al eliminar mensaje: {e}")

        # Obtener el canal de logs para enviar notificaciones al staff
        mod_settings = await self.get_moderation_settings(guild_id)
        log_channel_id = mod_settings.get("log_channel_id")
        log_channel = self.bot.get_channel(log_channel_id) if log_channel_id else None

        # Comprobar si se ha alcanzado el límite de advertencias para mutear
        if current_warnings >= MAX_WARNINGS_BEFORE_MUTE:
            # --- Proceso de Mute ---
            # Intentar encontrar un rol llamado "Muted"
            mute_role = discord.utils.get(member.guild.roles, name="Muted")

            # Si el rol "Muted" no existe, el bot intentará crearlo y configurar sus permisos
            if not mute_role:
                try:
                    # Crear el rol "Muted" con permisos para NO enviar mensajes y NO añadir reacciones
                    mute_role = await member.guild.create_role(
                        name="Muted",
                        permissions=discord.Permissions(
                            send_messages=False,
                            add_reactions=False,
                            speak=False # También silenciar en canales de voz
                        ),
                        reason="Rol 'Muted' creado por el bot para moderación automática."
                    )
                    # Sobreescribir permisos del rol "Muted" en todos los canales existentes
                    for channel in member.guild.channels:
                        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                            await channel.set_permissions(mute_role, send_messages=False, add_reactions=False, speak=False)
                    print(f"Rol 'Muted' creado y permisos configurados en el servidor '{member.guild.name}'.")
                    # Intenta enviar un mensaje al canal donde ocurrió la infracción o un canal general
                    if message_to_delete and message_to_delete.channel:
                        await message_to_delete.channel.send(f"🚨 ¡Se ha creado y configurado el rol 'Muted' en este servidor!.")
                except discord.Forbidden:
                    # Si no tiene permisos para crear el rol, notifica al canal
                    if message_to_delete and message_to_delete.channel:
                        await message_to_delete.channel.send(f"❌ No tengo permisos para crear el rol 'Muted'. Por favor, crea un rol 'Muted' manualmente con permisos de `No enviar mensajes` en los canales, y luego asigna al bot un rol con `Gestionar Roles` por encima del rol 'Muted'.")
                    await self.send_mod_log(log_channel, "❌ ERROR: No se pudo Mutear", f"No pude mutear a {member.name} ({member.id})", member, "Mute Fallido", "El bot no tiene permisos para crear o gestionar el rol 'Muted'.", discord.Color.red(), message_to_delete.jump_url if message_to_delete else None)
                    return # Salir si no se puede mutear

            try:
                await member.add_roles(mute_role, reason=f"Mute automático por acumular {MAX_WARNINGS_BEFORE_MUTE} advertencias: {reason}")
                if message_to_delete and message_to_delete.channel:
                    await message_to_delete.channel.send(f"🔇 {member.mention} ha sido muteado por {MUTE_DURATION_SECONDS // 60} minutos por acumular {MAX_WARNINGS_BEFORE_MUTE} advertencias. Razón: {reason}")
                await self.send_mod_log(log_channel, "🔇 Usuario Muteado Automáticamente", f"{member.name} ha sido muteado por acumular {MAX_WARNINGS_BEFORE_MUTE} advertencias.", member, "Mute Automático", reason, discord.Color.greyple(), message_to_delete.jump_url if message_to_delete else None)
                
                # Resetear advertencias después de mutear para que pueda volver a ser advertido tras el mute
                await self.bot.db.user_moderation_data.update_one(
                    {"_id": f"{guild_id}-{user_id}"},
                    {"$set": {"warnings": 0}}
                )

                # Si el mute es temporal, programar su remoción
                if MUTE_DURATION_SECONDS > 0:
                    await asyncio.sleep(MUTE_DURATION_SECONDS)
                    # Re-obtener el miembro en caso de que ya no esté en el servidor
                    member_after_sleep = member.guild.get_member(member.id)
                    if member_after_sleep and mute_role in member_after_sleep.roles:
                        await member_after_sleep.remove_roles(mute_role, reason="Fin de mute automático.")
                        if message_to_delete and message_to_delete.channel:
                            await message_to_delete.channel.send(f"✅ {member.mention} ha sido desmuteado automáticamente.")
                        await self.send_mod_log(log_channel, "✅ Usuario Desmuteado Automáticamente", f"{member.name} ha sido desmuteado.", member, "Desmute Automático", "Fin de la duración del mute.", discord.Color.green())

            except discord.Forbidden:
                if message_to_delete and message_to_delete.channel:
                    await message_to_delete.channel.send(f"❌ No tengo permisos para asignar el rol 'Muted' a {member.mention}.")
                await self.send_mod_log(log_channel, "❌ ERROR: No se pudo Mutear", f"No pude mutear a {member.name} ({member.id})", member, "Mute Fallido", "El bot no tiene permisos para añadir el rol 'Muted'.", discord.Color.red(), message_to_delete.jump_url if message_to_delete else None)
            except Exception as e:
                if message_to_delete and message_to_delete.channel:
                    await message_to_delete.channel.send(f"❌ Ocurrió un error al mutear a {member.mention}: {e}")
                await self.send_mod_log(log_channel, "❌ ERROR: Mute Fallido", f"Error al mutear a {member.name} ({member.id})", member, "Mute Fallido", f"Error interno: {e}", discord.Color.red(), message_to_delete.jump_url if message_to_delete else None)
        else:
            # --- Proceso de Advertencia ---
            if message_to_delete and message_to_delete.channel:
                await message_to_delete.channel.send(f"⚠️ {member.mention}, has sido advertido. Razón: {reason} ({current_warnings}/{MAX_WARNINGS_BEFORE_MUTE} advertencias antes de un mute).")
            await self.send_mod_log(log_channel, "⚠️ Usuario Advertido", f"{member.name} ha recibido una advertencia.", member, "Advertencia", reason, discord.Color.gold(), message_to_delete.jump_url if message_to_delete else None)

    # --- Evento on_message para Detección de Moderación ---
    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Este evento se activa cada vez que se envía un mensaje en el servidor.
        Aquí se implementa la lógica de anti-spam, anti-links y filtro de palabras.
        """
        # 1. Ignorar mensajes del propio bot para evitar bucles infinitos
        if message.author == self.bot.user:
            return

        # 2. Ignorar mensajes de otros bots (puedes cambiar esto si quieres moderar otros bots)
        if message.author.bot:
            # Importante: Permitir que los comandos de otros bots o los comandos del propio bot se procesen
            await self.bot.process_commands(message)
            return

        # 3. Solo aplicar moderación en servidores (no en mensajes directos)
        if message.guild is None:
            await self.bot.process_commands(message) # Permite que los comandos funcionen en DM
            return

        # 4. Obtener la configuración de moderación para este servidor
        guild_id = message.guild.id
        mod_settings = await self.get_moderation_settings(guild_id)
        prohibited_words = mod_settings.get("prohibited_words", [])
        allowed_links = mod_settings.get("allowed_links", [])
        log_channel_id = mod_settings.get("log_channel_id")
        
        # Intentamos obtener el objeto del canal de logs, si está configurado
        log_channel = self.bot.get_channel(log_channel_id) if log_channel_id else None

        # --- Lógica de Detección en el mensaje ---

        # Anti-Palabras Prohibidas
        content_lower = message.content.lower()
        for word in prohibited_words:
            # Usamos re.search con boundaries para evitar 'palabra' dentro de 'otra_palabra'
            # re.escape(word) se usa para que caracteres especiales en la palabra prohibida sean tratados literalmente
            if re.search(r'\b' + re.escape(word) + r'\b', content_lower):
                await self.warn_or_mute_user(message.author, f"Uso de palabra prohibida: '{word}'", message)
                return # Detener procesamiento si se detecta palabra prohibida

        # Anti-Links (detección de URLs no permitidas)
        # Patrón regex para detectar URLs (protocolo http/https, seguido de dominio, etc.)
        url_pattern = r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
        found_urls = re.findall(url_pattern, message.content)

        if found_urls:
            is_allowed = False
            for url in found_urls:
                # Comprobar si la URL encontrada empieza con alguno de los enlaces permitidos
                # Convierte ambos a minúsculas para una comparación sin distinción
                if any(url.lower().startswith(allowed_link.lower()) for allowed_link in allowed_links):
                    is_allowed = True
                    break # Si encuentra una URL permitida, puede salir del bucle
            
            if not is_allowed:
                await self.warn_or_mute_user(message.author, f"Envío de enlace no permitido: '{found_urls[0]}'", message)
                return # Detener procesamiento si se detecta link no permitido

        # Anti-Spam (basado en frecuencia de mensajes)
        current_time = time.time()
        user_id = message.author.id

        # Asegurarse de que las estructuras globales están inicializadas para el guild y el usuario
        if guild_id not in spam_detection:
            spam_detection[guild_id] = {}
        if user_id not in spam_detection[guild_id]:
            spam_detection[guild_id][user_id] = []
        
        # Limpiar timestamps antiguos (solo mantener los dentro del umbral de tiempo)
        spam_detection[guild_id][user_id] = [
            t for t in spam_detection[guild_id][user_id] if current_time - t < SPAM_THRESHOLD_TIME
        ]
        spam_detection[guild_id][user_id].append(current_time) # Añadir el timestamp del mensaje actual

        if len(spam_detection[guild_id][user_id]) >= SPAM_THRESHOLD_COUNT:
            # Se detectó spam por frecuencia
            await self.warn_or_mute_user(message.author, f"Spam detectado (demasiados mensajes en {SPAM_THRESHOLD_TIME} segundos).", message)
            spam_detection[guild_id][user_id].clear() # Limpiar la lista para este usuario para evitar spam repetido inmediato
            return # Detener procesamiento

        # Anti-Spam (basado en repetición de mensajes idénticos)
        # Almacenar el contenido del mensaje en minúsculas y sin espacios extra
        clean_content = message.content.lower().strip()

        if guild_id not in recent_messages:
            recent_messages[guild_id] = {}
        if user_id not in recent_messages[guild_id]:
            recent_messages[guild_id][user_id] = {"last_message_content": "", "last_message_count": 0}

        last_msg_data = recent_messages[guild_id][user_id]

        if clean_content == last_msg_data["last_message_content"] and clean_content: # También verificar que no esté vacío
            last_msg_data["last_message_count"] += 1
            if last_msg_data["last_message_count"] >= SPAM_REPETITION_THRESHOLD:
                await self.warn_or_mute_user(message.author, f"Spam detectado (mensaje idéntico repetido {SPAM_REPETITION_THRESHOLD} veces).", message)
                last_msg_data["last_message_count"] = 0 # Resetear el contador
                return # Detener procesamiento
        else:
            # Si el mensaje es diferente, resetear el rastreo de repetición
            last_msg_data["last_message_content"] = clean_content
            last_msg_data["last_message_count"] = 1

        # --- IMPORTANTE: Procesar los comandos del bot ---
        # Esta línea asegura que, después de toda la lógica de moderación,
        # el bot aún procese los comandos que el usuario pudo haber escrito (ej. !ping, !setbienvenida).
        await self.bot.process_commands(message)

    # --- Comandos de Moderación ---

    @commands.command(name='setmodlogs')
    @commands.has_permissions(manage_guild=True) # Solo usuarios con permiso para gestionar el servidor
    async def set_mod_logs(self, ctx, channel: discord.TextChannel):
        """
        Configura el canal para los logs de moderación automática.
        Uso: !setmodlogs #nombre-del-canal
        """
        if self.bot.db is None:
            await ctx.send("❌ Error: La base de datos no está conectada. No se pudo configurar el canal de logs.")
            return

        guild_id = ctx.guild.id
        try:
            await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$set": {"log_channel_id": channel.id}},
                upsert=True # Si no existe, lo crea; si existe, lo actualiza
            )
            await ctx.send(f"✅ ¡El canal de logs de moderación se ha configurado a {channel.mention} con éxito!")
            print(f"Canal de logs de moderación configurado a {channel.name} ({channel.id}) para el servidor '{ctx.guild.name}'.")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al configurar el canal de logs: {e}")
            print(f"Error al configurar el canal de logs de moderación: {e}")


    @commands.command(name='addword')
    @commands.has_permissions(manage_messages=True) # Permiso para gestionar mensajes
    async def add_prohibited_word(self, ctx, *, word: str): # Usamos '*' para que 'word' capture todo el resto del argumento
        """
        Añade una palabra o frase a la lista de palabras prohibidas del servidor.
        Uso: !addword <palabra_o_frase>
        """
        if self.bot.db is None: return await ctx.send("❌ Error: La base de datos no está conectada.")

        guild_id = ctx.guild.id
        word = word.lower().strip() # Convertimos a minúsculas y quitamos espacios en blanco
        if not word:
            return await ctx.send("❌ Por favor, especifica una palabra o frase para añadir.")

        try:
            # $addToSet añade un elemento a un array si no existe, evitando duplicados
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$addToSet": {"prohibited_words": word}},
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id: # modified_count si ya existía y se actualizó, upserted_id si se creó
                await ctx.send(f"✅ `'{word}'` ha sido añadida a las palabras prohibidas.")
            else:
                await ctx.send(f"⚠️ `'{word}'` ya estaba en la lista de palabras prohibidas.")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al añadir la palabra: {e}")


    @commands.command(name='removeword')
    @commands.has_permissions(manage_messages=True)
    async def remove_prohibited_word(self, ctx, *, word: str):
        """
        Quita una palabra o frase de la lista de palabras prohibidas del servidor.
        Uso: !removeword <palabra_o_frase>
        """
        if self.bot.db is None: return await ctx.send("❌ Error: La base de datos no está conectada.")

        guild_id = ctx.guild.id
        word = word.lower().strip()
        if not word:
            return await ctx.send("❌ Por favor, especifica una palabra o frase para eliminar.")

        try:
            # $pull elimina un elemento de un array
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$pull": {"prohibited_words": word}}
            )
            if result.modified_count > 0:
                await ctx.send(f"✅ `'{word}'` ha sido eliminada de las palabras prohibidas.")
            else:
                await ctx.send(f"⚠️ `'{word}'` no se encontró en la lista de palabras prohibidas.")
        except Exception as e:
                await ctx.send(f"❌ Ocurrió un error al eliminar la palabra: {e}")


    @commands.command(name='listwords')
    @commands.has_permissions(manage_messages=True)
    async def list_prohibited_words(self, ctx):
        """
        Muestra la lista de palabras prohibidas configuradas para este servidor.
        Uso: !listwords
        """
        if self.bot.db is None: return await ctx.send("❌ Error: La base de datos no está conectada.")

        guild_id = ctx.guild.id
        settings = await self.get_moderation_settings(guild_id)
        prohibited_words = settings.get("prohibited_words", [])

        if prohibited_words:
            words_list = "\n".join([f"- {w}" for w in sorted(prohibited_words)]) # Las ordenamos alfabéticamente
            embed = discord.Embed(
                title="🚫 Palabras Prohibidas del Servidor",
                description=f"Las siguientes palabras están prohibidas:\n```\n{words_list}\n```",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("ℹ️ No hay palabras prohibidas configuradas para este servidor. ¡Usa `!addword <palabra>` para añadir una!")

    @commands.command(name='addlink')
    @commands.has_permissions(manage_messages=True)
    async def add_allowed_link(self, ctx, *, link: str):
        """
        Añade un dominio o patrón de enlace a la lista de enlaces permitidos.
        Uso: !addlink <dominio.com/patron>
        """
        if self.bot.db is None: return await ctx.send("❌ Error: La base de datos no está conectada.")
        
        guild_id = ctx.guild.id
        link = link.lower().strip()
        if not link:
            return await ctx.send("❌ Por favor, especifica un enlace o patrón de dominio a añadir (ej. `youtube.com/`, `discord.gg/`).")

        try:
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$addToSet": {"allowed_links": link}},
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id:
                await ctx.send(f"✅ `'{link}'` ha sido añadido a los enlaces permitidos.")
            else:
                await ctx.send(f"⚠️ `'{link}'` ya estaba en la lista de enlaces permitidos.")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al añadir el enlace: {e}")

    @commands.command(name='removelink')
    @commands.has_permissions(manage_messages=True)
    async def remove_allowed_link(self, ctx, *, link: str):
        """
        Quita un dominio o patrón de enlace de la lista de enlaces permitidos.
        Uso: !removelink <dominio.com/patron>
        """
        if self.bot.db is None: return await ctx.send("❌ Error: La base de datos no está conectada.")
        
        guild_id = ctx.guild.id
        link = link.lower().strip()
        if not link:
            return await ctx.send("❌ Por favor, especifica un enlace o patrón de dominio a eliminar.")

        try:
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$pull": {"allowed_links": link}}
            )
            if result.modified_count > 0:
                await ctx.send(f"✅ `'{link}'` ha sido eliminado de los enlaces permitidos.")
            else:
                await ctx.send(f"⚠️ `'{link}'` no se encontró en la lista de enlaces permitidos.")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al eliminar el enlace: {e}")

    @commands.command(name='listlinks')
    @commands.has_permissions(manage_messages=True)
    async def list_allowed_links(self, ctx):
        """
        Muestra la lista de enlaces permitidos configurados para este servidor.
        Uso: !listlinks
        """
        if self.bot.db is None: return await ctx.send("❌ Error: La base de datos no está conectada.")
        
        guild_id = ctx.guild.id
        settings = await self.get_moderation_settings(guild_id)
        allowed_links = settings.get("allowed_links", [])

        if allowed_links:
            links_list = "\n".join([f"- {l}" for l in sorted(allowed_links)])
            embed = discord.Embed(
                title="🔗 Enlaces Permitidos del Servidor",
                description=f"Los siguientes dominios/patrones de enlace están permitidos:\n```\n{links_list}\n```",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("ℹ️ No hay enlaces permitidos configurados para este servidor. ¡Usa `!addlink <dominio.com/>` para añadir uno!")


# Esta función es CRUCIAL para que discord.py pueda cargar el Cog.
# Deberá ser llamada desde main.py con bot.load_extension()
async def setup(bot):
    await bot.add_cog(Moderation(bot))