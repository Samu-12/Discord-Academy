import discord
from discord.ext import commands
from discord import app_commands
import asyncio

# Constantes para la configuración del sistema de tickets
DEFAULT_TICKET_CATEGORY_NAME = "Tickets"
DEFAULT_TICKET_CHANNEL_PREFIX = "ticket-"
TICKET_LOG_CHANNEL_NAME = "ticket-logs" # Canal donde se registrarán aperturas/cierres
SUPPORT_ROLE_NAME = "Soporte" # Rol que podrá ver y gestionar los tickets

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_ticket_settings(self, guild_id):
        """Obtiene la configuración de tickets para un servidor desde la base de datos."""
        if self.bot.db is None:
            print("Error: La base de datos no está conectada para obtener configuración de tickets.")
            return {}
        settings = await self.bot.db.ticket_settings.find_one({"_id": guild_id})
        if settings:
            return settings
        return {
            "ticket_category_id": None,
            "ticket_log_channel_id": None,
            "support_role_id": None
        }

    async def send_ticket_log(self, guild, embed_title, description, user, action_type, color, ticket_channel=None, closed_by=None, reason=None):
        """Envía un log al canal de logs de tickets."""
        settings = await self.get_ticket_settings(guild.id)
        log_channel_id = settings.get("ticket_log_channel_id")
        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

        if log_channel:
            log_embed = discord.Embed(
                title=embed_title,
                description=description,
                color=color
            )
            log_embed.add_field(name="Usuario", value=user.mention, inline=True)
            log_embed.add_field(name="ID de Usuario", value=user.id, inline=True)
            log_embed.add_field(name="Acción", value=action_type, inline=True)
            if ticket_channel:
                log_embed.add_field(name="Canal de Ticket", value=ticket_channel.mention, inline=True)
            if closed_by:
                log_embed.add_field(name="Cerrado Por", value=closed_by.mention, inline=True)
            if reason:
                log_embed.add_field(name="Razón", value=reason, inline=False)

            log_embed.set_footer(text=f"Servidor: {guild.name}")
            log_embed.timestamp = discord.utils.utcnow()

            try:
                await log_channel.send(embed=log_embed)
            except discord.Forbidden:
                print(f"ERROR: El bot no tiene permisos para enviar logs en el canal de tickets {log_channel.name} ({log_channel.id}).")
            except Exception as e:
                print(f"ERROR al enviar log de tickets: {e}")
        else:
            print(f"TICKET_LOG: {action_type} - {user.name} | Canal: {ticket_channel.name if ticket_channel else 'N/A'}")

    # --- Comandos de Configuración de Tickets (Solo Comandos de Barra) ---

    @app_commands.command(name="setticketcategory", description="Configura la categoría donde se crearán los tickets.")
    @app_commands.describe(category="La categoría donde se crearán los tickets.")
    @app_commands.default_permissions(manage_channels=True)
    async def set_ticket_category_slash(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        await interaction.response.defer(ephemeral=True)
        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)

        try:
            await self.bot.db.ticket_settings.update_one(
                {"_id": interaction.guild_id},
                {"$set": {"ticket_category_id": category.id}},
                upsert=True
            )
            await interaction.followup.send(f"✅ ¡La categoría para tickets se ha configurado a `{category.name}` con éxito!", ephemeral=True)
            print(f"Categoría de tickets configurada a {category.name} ({category.id}) para el servidor '{interaction.guild.name}'.")
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al configurar la categoría: {e}", ephemeral=True)
            print(f"Error al configurar la categoría de tickets: {e}")

    @app_commands.command(name="setticketlogs", description="Configura el canal para los logs de tickets.")
    @app_commands.describe(channel="El canal de texto para los logs de tickets.")
    @app_commands.default_permissions(manage_channels=True)
    async def set_ticket_logs_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)

        try:
            await self.bot.db.ticket_settings.update_one(
                {"_id": interaction.guild_id},
                {"$set": {"ticket_log_channel_id": channel.id}},
                upsert=True
            )
            await interaction.followup.send(f"✅ ¡El canal de logs de tickets se ha configurado a {channel.mention} con éxito!", ephemeral=True)
            print(f"Canal de logs de tickets configurado a {channel.name} ({channel.id}) para el servidor '{interaction.guild.name}'.")
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al configurar el canal de logs de tickets: {e}", ephemeral=True)
            print(f"Error al configurar el canal de logs de tickets: {e}")

    @app_commands.command(name="setsupportrole", description="Configura el rol de soporte para gestionar tickets.")
    @app_commands.describe(role="El rol que tendrá acceso a los canales de tickets.")
    @app_commands.default_permissions(manage_roles=True)
    async def set_support_role_slash(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)

        try:
            await self.bot.db.ticket_settings.update_one(
                {"_id": interaction.guild_id},
                {"$set": {"support_role_id": role.id}},
                upsert=True
            )
            await interaction.followup.send(f"✅ ¡El rol de soporte para tickets se ha configurado a `{role.name}` con éxito!", ephemeral=True)
            print(f"Rol de soporte configurado a {role.name} ({role.id}) para el servidor '{interaction.guild.name}'.")
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al configurar el rol de soporte: {e}", ephemeral=True)
            print(f"Error al configurar el rol de soporte: {e}")

    # --- Comandos para Gestión de Tickets ---

    @app_commands.command(name="ticket", description="Abre un nuevo ticket de soporte.")
    @app_commands.describe(reason="La razón por la que abres el ticket (opcional).")
    async def open_ticket_slash(self, interaction: discord.Interaction, reason: str = "Sin razón especificada."):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            return await interaction.followup.send("Este comando solo puede ser usado en un servidor.", ephemeral=True)

        settings = await self.get_ticket_settings(interaction.guild_id)
        category_id = settings.get("ticket_category_id")
        support_role_id = settings.get("support_role_id")

        if not category_id:
            return await interaction.followup.send(f"❌ El sistema de tickets no está configurado. Un administrador debe usar `/setticketcategory` para configurar una categoría y `/setsupportrole` para configurar un rol de soporte.", ephemeral=True)

        category = interaction.guild.get_channel(category_id)
        if not category:
            return await interaction.followup.send("❌ La categoría de tickets configurada no existe. Por favor, pídale a un administrador que la reconfigure.", ephemeral=True)

        # Verificar si el usuario ya tiene un ticket abierto
        for channel in category.channels:
            if channel.name.startswith(DEFAULT_TICKET_CHANNEL_PREFIX) and interaction.user.id in [m.id for m in channel.members]:
                return await interaction.followup.send(f"⚠️ Ya tienes un ticket abierto en {channel.mention}. Por favor, ciérralo antes de abrir uno nuevo.", ephemeral=True)

        # Permisos del canal del ticket
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True),
            self.bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True, manage_channels=True)
        }

        support_role = None
        if support_role_id:
            support_role = interaction.guild.get_role(support_role_id)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True)
            else:
                await interaction.followup.send(f"⚠️ El rol de soporte configurado no existe. Los miembros de soporte no podrán ver el ticket a menos que el rol sea reconfigurado.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ No hay un rol de soporte configurado. Asegúrate de que un administrador use `/setsupportrole` para que el personal de soporte pueda ver los tickets.", ephemeral=True)

        ticket_channel_name = f"{DEFAULT_TICKET_CHANNEL_PREFIX}{interaction.user.name.replace(' ', '-').lower()}-{interaction.user.discriminator if hasattr(interaction.user, 'discriminator') else interaction.user.id}"[:100]

        try:
            ticket_channel = await interaction.guild.create_text_channel(
                ticket_channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket abierto por {interaction.user.name}"
            )
            await interaction.followup.send(f"✅ Tu ticket ha sido creado: {ticket_channel.mention}", ephemeral=True)

            ticket_embed = discord.Embed(
                title=f"🎫 Ticket de {interaction.user.display_name}",
                description=f"**Usuario:** {interaction.user.mention}\n**ID:** `{interaction.user.id}`\n**Razón:** {reason}",
                color=discord.Color.blue()
            )
            ticket_embed.add_field(name="Información", value="Un miembro del equipo de soporte te atenderá en breve. Para cerrar este ticket, usa el comando `/close`.", inline=False)
            ticket_embed.set_footer(text="Gracias por tu paciencia.")
            ticket_embed.timestamp = discord.utils.utcnow()

            await ticket_channel.send(f"{interaction.user.mention}" + (f" {support_role.mention}" if support_role else ""), embed=ticket_embed)
            
            # Log la apertura del ticket
            await self.send_ticket_log(
                interaction.guild,
                "🎫 Ticket Abierto",
                f"**Usuario:** {interaction.user.mention} ha abierto un ticket.",
                interaction.user,
                "Apertura",
                discord.Color.blue(),
                ticket_channel
            )

        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos para crear canales o configurar los permisos necesarios. Asegúrate de que mi rol tenga `Gestionar Canales` y esté por encima de los roles de los usuarios en la jerarquía.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al abrir el ticket: {e}", ephemeral=True)
            print(f"Error al abrir ticket: {e}")

    @app_commands.command(name="close", description="Cierra el ticket actual.")
    @app_commands.describe(reason="La razón por la que se cierra el ticket (opcional).")
    async def close_ticket_slash(self, interaction: discord.Interaction, reason: str = "Sin razón especificada."):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            return await interaction.followup.send("Este comando solo puede ser usado en un servidor.", ephemeral=True)

        if not interaction.channel.name.startswith(DEFAULT_TICKET_CHANNEL_PREFIX):
            return await interaction.followup.send("❌ Este comando solo puede usarse dentro de un canal de ticket.", ephemeral=True)
        
        # Verificar si el usuario que cierra es el creador del ticket o un miembro de soporte/admin
        is_ticket_creator = interaction.channel.permissions_for(interaction.user).read_messages and interaction.user.id == int(interaction.channel.name.split('-')[-1]) # Asumiendo que el ID es la última parte del nombre del canal
        
        settings = await self.get_ticket_settings(interaction.guild_id)
        support_role_id = settings.get("support_role_id")
        is_support_member = False
        if support_role_id:
            support_role = interaction.guild.get_role(support_role_id)
            if support_role and support_role in interaction.user.roles:
                is_support_member = True

        if not (is_ticket_creator or is_support_member or interaction.user.guild_permissions.manage_channels):
            return await interaction.followup.send("❌ Solo el creador del ticket, un miembro de soporte o un administrador pueden cerrar este ticket.", ephemeral=True)

        try:
            await interaction.followup.send(f"✅ El ticket será cerrado en unos segundos. Razón: {reason}", ephemeral=True)
            await interaction.channel.send("Este ticket se cerrará en 5 segundos...")
            await asyncio.sleep(5)
            
            # Intentar obtener el usuario que creó el ticket del nombre del canal
            creator_id = None
            try:
                # Extraer el ID del usuario del nombre del canal. 
                # Si el nombre es ticket-usuario-123456789012345678, el ID es 123456789012345678
                parts = interaction.channel.name.split('-')
                if len(parts) > 1 and parts[-1].isdigit():
                    creator_id = int(parts[-1])
            except ValueError:
                pass # No se pudo extraer el ID, no crítico para el cierre

            ticket_creator = interaction.guild.get_member(creator_id) if creator_id else None

            await self.send_ticket_log(
                interaction.guild,
                "✅ Ticket Cerrado",
                f"**Usuario:** {ticket_creator.mention if ticket_creator else 'ID desconocido'} (creador) ha visto su ticket cerrado.",
                ticket_creator if ticket_creator else interaction.user, # Usar el creador si se encontró, sino el que cerró
                "Cierre",
                discord.Color.green(),
                interaction.channel,
                interaction.user,
                reason
            )

            await interaction.channel.delete(reason=f"Ticket cerrado por {interaction.user.name}: {reason}")

        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos para eliminar canales. Asegúrate de que mi rol tenga `Gestionar Canales` y esté por encima de la categoría de tickets.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al cerrar el ticket: {e}", ephemeral=True)
            print(f"Error al cerrar ticket: {e}")

# Función de configuración del Cog
async def setup(bot):
    await bot.add_cog(Tickets(bot))