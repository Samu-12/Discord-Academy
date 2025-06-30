import discord
from discord.ext import commands
import re
import time
import asyncio

# Importar app_commands para comandos de barra
from discord import app_commands

# Diccionarios para almacenar datos temporales de spam y usuarios en la memoria del bot.
spam_detection = {}
recent_messages = {}

# Constantes de configuración para la moderación
SPAM_THRESHOLD_TIME = 5
SPAM_THRESHOLD_COUNT = 5
SPAM_REPETITION_THRESHOLD = 3

MAX_WARNINGS_BEFORE_MUTE = 3
MUTE_DURATION_SECONDS = 600 # 10 minutos

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- Funciones Auxiliares (sin cambios, ya que son internas del Cog) ---
    async def get_moderation_settings(self, guild_id):
        """
        Obtiene la configuración de moderación (palabras prohibidas, enlaces permitidos, canal de logs)
        desde la base de datos para un servidor específico.
        """
        if self.bot.db is None:
            print("Error: La base de datos no está conectada para obtener configuración de moderación.")
            return {}
        settings = await self.bot.db.moderation_settings.find_one({"_id": guild_id})
        if settings:
            return settings
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
            log_embed.timestamp = discord.utils.utcnow()

            if message_link:
                log_embed.add_field(name="Mensaje", value=f"[Ir al Mensaje]({message_link})", inline=False)

            try:
                await log_channel.send(embed=log_embed)
            except discord.Forbidden:
                print(f"ERROR: El bot no tiene permisos para enviar logs en el canal {log_channel.name} ({log_channel.id}).")
            except Exception as e:
                print(f"ERROR al enviar log de moderación: {e}")
        else:
            print(f"MOD_LOG: {action_type} - {offender.name} | Razón: {reason}")

    async def warn_or_mute_user(self, member, reason, message_to_delete=None):
        """
        Maneja el sistema de advertencias y muteo automático para un usuario.
        """
        user_id = member.id
        guild_id = member.guild.id

        user_data = await self.bot.db.user_moderation_data.find_one({"_id": f"{guild_id}-{user_id}"})
        current_warnings = user_data.get("warnings", 0) if user_data else 0

        current_warnings += 1

        await self.bot.db.user_moderation_data.update_one(
            {"_id": f"{guild_id}-{user_id}"},
            {"$set": {"warnings": current_warnings, "last_warn_timestamp": discord.utils.utcnow()}},
            upsert=True
        )

        if message_to_delete:
            try:
                await message_to_delete.delete()
            except discord.Forbidden:
                print(f"ERROR: No tengo permisos para eliminar el mensaje en {message_to_delete.channel.name} por {member.name}.")
            except Exception as e:
                print(f"ERROR al eliminar mensaje: {e}")

        mod_settings = await self.get_moderation_settings(guild_id)
        log_channel_id = mod_settings.get("log_channel_id")
        log_channel = self.bot.get_channel(log_channel_id) if log_channel_id else None

        if current_warnings >= MAX_WARNINGS_BEFORE_MUTE:
            mute_role = discord.utils.get(member.guild.roles, name="Muted")

            if not mute_role:
                try:
                    mute_role = await member.guild.create_role(
                        name="Muted",
                        permissions=discord.Permissions(
                            send_messages=False,
                            add_reactions=False,
                            speak=False
                        ),
                        reason="Rol 'Muted' creado por el bot para moderación automática."
                    )
                    for channel in member.guild.channels:
                        if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                            await channel.set_permissions(mute_role, send_messages=False, add_reactions=False, speak=False)
                    print(f"Rol 'Muted' creado y permisos configurados en el servidor '{member.guild.name}'.")
                    if message_to_delete and message_to_delete.channel:
                        await message_to_delete.channel.send(f"🚨 ¡Se ha creado y configurado el rol 'Muted' en este servidor!.")
                except discord.Forbidden:
                    if message_to_delete and message_to_delete.channel:
                        await message_to_delete.channel.send(f"❌ No tengo permisos para crear el rol 'Muted'. Por favor, crea un rol 'Muted' manualmente con permisos de `No enviar mensajes` en los canales, y luego asigna al bot un rol con `Gestionar Roles` por encima del rol 'Muted'.")
                    await self.send_mod_log(log_channel, "❌ ERROR: No se pudo Mutear", f"No pude mutear a {member.name} ({member.id})", member, "Mute Fallido", "El bot no tiene permisos para crear o gestionar el rol 'Muted'.", discord.Color.red(), message_to_delete.jump_url if message_to_delete else None)
                    return

            try:
                await member.add_roles(mute_role, reason=f"Mute automático por acumular {MAX_WARNINGS_BEFORE_MUTE} advertencias: {reason}")
                if message_to_delete and message_to_delete.channel:
                    await message_to_delete.channel.send(f"🔇 {member.mention} ha sido muteado por {MUTE_DURATION_SECONDS // 60} minutos por acumular {MAX_WARNINGS_BEFORE_MUTE} advertencias. Razón: {reason}")
                await self.send_mod_log(log_channel, "🔇 Usuario Muteado Automáticamente", f"{member.name} ha sido muteado por acumular {MAX_WARNINGS_BEFORE_MUTE} advertencias.", member, "Mute Automático", reason, discord.Color.greyple(), message_to_delete.jump_url if message_to_delete else None)

                await self.bot.db.user_moderation_data.update_one(
                    {"_id": f"{guild_id}-{user_id}"},
                    {"$set": {"warnings": 0}}
                )

                if MUTE_DURATION_SECONDS > 0:
                    await asyncio.sleep(MUTE_DURATION_SECONDS)
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
            if message_to_delete and message_to_delete.channel:
                await message_to_delete.channel.send(f"⚠️ {member.mention}, has sido advertido. Razón: {reason} ({current_warnings}/{MAX_WARNINGS_BEFORE_MUTE} advertencias antes de un mute).")
            await self.send_mod_log(log_channel, "⚠️ Usuario Advertido", f"{member.name} ha recibido una advertencia.", member, "Advertencia", reason, discord.Color.gold(), message_to_delete.jump_url if message_to_delete else None)


    # --- Evento on_message para Detección de Moderación (sin cambios) ---
    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Este evento se activa cada vez que se envía un mensaje en el servidor.
        Aquí se implementa la lógica de anti-spam, anti-links y filtro de palabras.
        """
        if message.author == self.bot.user:
            return

        if message.author.bot:
            await self.bot.process_commands(message)
            return

        if message.guild is None:
            await self.bot.process_commands(message)
            return

        guild_id = message.guild.id
        mod_settings = await self.get_moderation_settings(guild_id)
        prohibited_words = mod_settings.get("prohibited_words", [])
        allowed_links = mod_settings.get("allowed_links", [])
        log_channel_id = mod_settings.get("log_channel_id")
        
        log_channel = self.bot.get_channel(log_channel_id) if log_channel_id else None

        content_lower = message.content.lower()
        for word in prohibited_words:
            if re.search(r'\b' + re.escape(word) + r'\b', content_lower):
                await self.warn_or_mute_user(message.author, f"Uso de palabra prohibida: '{word}'", message)
                return

        url_pattern = r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
        found_urls = re.findall(url_pattern, message.content)

        if found_urls:
            is_allowed = False
            for url in found_urls:
                if any(url.lower().startswith(allowed_link.lower()) for allowed_link in allowed_links):
                    is_allowed = True
                    break
            
            if not is_allowed:
                await self.warn_or_mute_user(message.author, f"Envío de enlace no permitido: '{found_urls[0]}'", message)
                return

        current_time = time.time()
        user_id = message.author.id

        if guild_id not in spam_detection:
            spam_detection[guild_id] = {}
        if user_id not in spam_detection[guild_id]:
            spam_detection[guild_id][user_id] = []
        
        spam_detection[guild_id][user_id] = [
            t for t in spam_detection[guild_id][user_id] if current_time - t < SPAM_THRESHOLD_TIME
        ]
        spam_detection[guild_id][user_id].append(current_time)

        if len(spam_detection[guild_id][user_id]) >= SPAM_THRESHOLD_COUNT:
            await self.warn_or_mute_user(message.author, f"Spam detectado (demasiados mensajes en {SPAM_THRESHOLD_TIME} segundos).", message)
            spam_detection[guild_id][user_id].clear()
            return

        clean_content = message.content.lower().strip()

        if guild_id not in recent_messages:
            recent_messages[guild_id] = {}
        if user_id not in recent_messages[guild_id]:
            recent_messages[guild_id][user_id] = {"last_message_content": "", "last_message_count": 0}

        last_msg_data = recent_messages[guild_id][user_id]

        if clean_content == last_msg_data["last_message_content"] and clean_content:
            last_msg_data["last_message_count"] += 1
            if last_msg_data["last_message_count"] >= SPAM_REPETITION_THRESHOLD:
                await self.warn_or_mute_user(message.author, f"Spam detectado (mensaje idéntico repetido {SPAM_REPETITION_THRESHOLD} veces).", message)
                last_msg_data["last_message_count"] = 0
                return
        else:
            last_msg_data["last_message_content"] = clean_content
            last_msg_data["last_message_count"] = 1

        await self.bot.process_commands(message)


    # --- Comandos de Prefijo (exclamación) (se mantienen para compatibilidad o preferencia) ---

    @commands.command(name='setmodlogs')
    @commands.has_permissions(manage_guild=True)
    async def set_mod_logs_prefix(self, ctx, channel: discord.TextChannel):
        """
        [Prefijo] Configura el canal para los logs de moderación automática.
        Uso: !setmodlogs #nombre-del-canal
        """
        if self.bot.db is None: return await ctx.send("❌ Error: La base de datos no está conectada.")
        guild_id = ctx.guild.id
        try:
            await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$set": {"log_channel_id": channel.id}},
                upsert=True
            )
            await ctx.send(f"✅ ¡El canal de logs de moderación se ha configurado a {channel.mention} con éxito!")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al configurar el canal de logs: {e}")

    # ... (el resto de tus comandos de prefijo !addword, !removeword, !listwords, !addlink, !removelink, !listlinks) ...
    # Los he omitido aquí por brevedad, pero mantenlos en tu archivo.


    # --- NUEVOS COMANDOS DE BARRA (SLASH COMMANDS) ---
    # Para la insignia, al menos uno de estos comandos globales (sin guild_ids específicos)
    # debe ser usado y tu bot debe estar en 75 servidores o más.

    @app_commands.command(name="setmodlogs", description="Configura el canal para los logs de moderación automática.")
    @app_commands.describe(channel="El canal de texto para los logs de moderación.")
    @app_commands.default_permissions(manage_guild=True) # Requiere permiso de "Gestionar Servidor"
    async def set_mod_logs_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """
        [Barra] Configura el canal para los logs de moderación automática.
        """
        if self.bot.db is None:
            await interaction.response.send_message("❌ Error: La base de datos no está conectada.", ephemeral=True)
            return

        guild_id = interaction.guild_id
        try:
            await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$set": {"log_channel_id": channel.id}},
                upsert=True
            )
            await interaction.response.send_message(f"✅ ¡El canal de logs de moderación se ha configurado a {channel.mention} con éxito!", ephemeral=True)
            print(f"Canal de logs de moderación configurado a {channel.name} ({channel.id}) para el servidor '{interaction.guild.name}'.")
        except Exception as e:
            await interaction.response.send_message(f"❌ Ocurrió un error al configurar el canal de logs: {e}", ephemeral=True)
            print(f"Error al configurar el canal de logs de moderación: {e}")


    @app_commands.command(name="addword", description="Añade una palabra o frase a la lista de palabras prohibidas.")
    @app_commands.describe(word="La palabra o frase a prohibir.")
    @app_commands.default_permissions(manage_messages=True)
    async def add_prohibited_word_slash(self, interaction: discord.Interaction, word: str):
        """
        [Barra] Añade una palabra o frase a la lista de palabras prohibidas del servidor.
        """
        if self.bot.db is None:
            return await interaction.response.send_message("❌ Error: La base de datos no está conectada.", ephemeral=True)

        guild_id = interaction.guild_id
        word = word.lower().strip()
        if not word:
            return await interaction.response.send_message("❌ Por favor, especifica una palabra o frase para añadir.", ephemeral=True)

        try:
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$addToSet": {"prohibited_words": word}},
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id:
                await interaction.response.send_message(f"✅ `'{word}'` ha sido añadida a las palabras prohibidas.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ `'{word}'` ya estaba en la lista de palabras prohibidas.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ocurrió un error al añadir la palabra: {e}", ephemeral=True)


    @app_commands.command(name="removeword", description="Quita una palabra o frase de la lista de palabras prohibidas.")
    @app_commands.describe(word="La palabra o frase a eliminar.")
    @app_commands.default_permissions(manage_messages=True)
    async def remove_prohibited_word_slash(self, interaction: discord.Interaction, word: str):
        """
        [Barra] Quita una palabra o frase de la lista de palabras prohibidas del servidor.
        """
        if self.bot.db is None:
            return await interaction.response.send_message("❌ Error: La base de datos no está conectada.", ephemeral=True)

        guild_id = interaction.guild_id
        word = word.lower().strip()
        if not word:
            return await interaction.response.send_message("❌ Por favor, especifica una palabra o frase para eliminar.", ephemeral=True)

        try:
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$pull": {"prohibited_words": word}}
            )
            if result.modified_count > 0:
                await interaction.response.send_message(f"✅ `'{word}'` ha sido eliminada de las palabras prohibidas.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ `'{word}'` no se encontró en la lista de palabras prohibidas.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ocurrió un error al eliminar la palabra: {e}", ephemeral=True)


    @app_commands.command(name="listwords", description="Muestra la lista de palabras prohibidas.")
    @app_commands.default_permissions(manage_messages=True)
    async def list_prohibited_words_slash(self, interaction: discord.Interaction):
        """
        [Barra] Muestra la lista de palabras prohibidas configuradas para este servidor.
        """
        if self.bot.db is None:
            return await interaction.response.send_message("❌ Error: La base de datos no está conectada.", ephemeral=True)

        guild_id = interaction.guild_id
        settings = await self.get_moderation_settings(guild_id)
        prohibited_words = settings.get("prohibited_words", [])

        if prohibited_words:
            words_list = "\n".join([f"- {w}" for w in sorted(prohibited_words)])
            embed = discord.Embed(
                title="🚫 Palabras Prohibidas del Servidor",
                description=f"Las siguientes palabras están prohibidas:\n```\n{words_list}\n```",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ No hay palabras prohibidas configuradas para este servidor. ¡Usa `/addword <palabra>` para añadir una!", ephemeral=True)


    @app_commands.command(name="addlink", description="Añade un dominio o patrón de enlace a la lista de permitidos.")
    @app_commands.describe(link="El dominio o patrón de enlace a permitir (ej. discord.gg/).")
    @app_commands.default_permissions(manage_messages=True)
    async def add_allowed_link_slash(self, interaction: discord.Interaction, link: str):
        """
        [Barra] Añade un dominio o patrón de enlace a la lista de enlaces permitidos.
        """
        if self.bot.db is None:
            return await interaction.response.send_message("❌ Error: La base de datos no está conectada.", ephemeral=True)
        
        guild_id = interaction.guild_id
        link = link.lower().strip()
        if not link:
            return await interaction.response.send_message("❌ Por favor, especifica un enlace o patrón de dominio a añadir (ej. `youtube.com/`, `discord.gg/`).", ephemeral=True)

        try:
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$addToSet": {"allowed_links": link}},
                upsert=True
            )
            if result.modified_count > 0 or result.upserted_id:
                await interaction.response.send_message(f"✅ `'{link}'` ha sido añadido a los enlaces permitidos.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ `'{link}'` ya estaba en la lista de enlaces permitidos.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ocurrió un error al añadir el enlace: {e}", ephemeral=True)


    @app_commands.command(name="removelink", description="Quita un dominio o patrón de enlace de la lista de permitidos.")
    @app_commands.describe(link="El dominio o patrón de enlace a eliminar.")
    @app_commands.default_permissions(manage_messages=True)
    async def remove_allowed_link_slash(self, interaction: discord.Interaction, link: str):
        """
        [Barra] Quita un dominio o patrón de enlace de la lista de enlaces permitidos.
        """
        if self.bot.db is None:
            return await interaction.response.send_message("❌ Error: La base de datos no está conectada.", ephemeral=True)
        
        guild_id = interaction.guild_id
        link = link.lower().strip()
        if not link:
            return await interaction.response.send_message("❌ Por favor, especifica un enlace o patrón de dominio a eliminar.", ephemeral=True)

        try:
            result = await self.bot.db.moderation_settings.update_one(
                {"_id": guild_id},
                {"$pull": {"allowed_links": link}}
            )
            if result.modified_count > 0:
                await interaction.response.send_message(f"✅ `'{link}'` ha sido eliminado de los enlaces permitidos.", ephemeral=True)
            else:
                await interaction.response.send_message(f"⚠️ `'{link}'` no se encontró en la lista de enlaces permitidos.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ocurrió un error al eliminar el enlace: {e}", ephemeral=True)


    @app_commands.command(name="listlinks", description="Muestra la lista de enlaces permitidos.")
    @app_commands.default_permissions(manage_messages=True)
    async def list_allowed_links_slash(self, interaction: discord.Interaction):
        """
        [Barra] Muestra la lista de enlaces permitidos configurados para este servidor.
        """
        if self.bot.db is None:
            return await interaction.response.send_message("❌ Error: La base de datos no está conectada.", ephemeral=True)
        
        guild_id = interaction.guild_id
        settings = await self.get_moderation_settings(guild_id)
        allowed_links = settings.get("allowed_links", [])

        if allowed_links:
            links_list = "\n".join([f"- {l}" for l in sorted(allowed_links)])
            embed = discord.Embed(
                title="🔗 Enlaces Permitidos del Servidor",
                description=f"Los siguientes dominios/patrones de enlace están permitidos:\n```\n{links_list}\n```",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ No hay enlaces permitidos configurados para este servidor. ¡Usa `/addlink <dominio.com/>` para añadir uno!", ephemeral=True)


# Función de configuración del Cog
async def setup(bot):
    await bot.add_cog(Moderation(bot))
    # No es necesario llamar a tree.sync() aquí, lo haremos en main.py al cargar los cogs