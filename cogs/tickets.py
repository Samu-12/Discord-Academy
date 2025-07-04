import discord
from discord.ext import commands
from discord import app_commands, ui
import asyncio
import uuid 

# --- Constantes y configuraciones por defecto ---
DEFAULT_TICKET_CATEGORY_NAME = "Tickets Abiertos" 
DEFAULT_TICKET_CHANNEL_PREFIX = "ticket-"
TICKET_LOG_CHANNEL_NAME = "ticket-logs"
TICKET_RATING_LOG_CHANNEL_NAME = "ticket-ratings" 
SUPPORT_ROLE_NAME = "Soporte"

# --- Vistas (UI) para el sistema de tickets ---

# Clase para el botón de reclamar ticket
class ClaimTicketButton(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @ui.button(label="Reclamar Ticket", style=discord.ButtonStyle.green, emoji="🙋‍♂️", custom_id="claim_ticket_button")
    async def claim_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        cog = self.bot.get_cog("Tickets")
        if not cog:
            return await interaction.followup.send("❌ Error interno: El módulo de tickets no está cargado.", ephemeral=True)
        
        settings = await cog.get_ticket_settings(interaction.guild_id)
        support_role_id = settings.get("support_role_id")
        
        is_support_member = False
        if support_role_id:
            support_role = interaction.guild.get_role(support_role_id)
            if support_role and support_role in interaction.user.roles:
                is_support_member = True
        
        if not (is_support_member or interaction.user.guild_permissions.manage_channels):
            return await interaction.followup.send("❌ Solo el personal de soporte o un administrador pueden reclamar este ticket.", ephemeral=True)

        # Deshabilitar el botón una vez reclamado
        button.disabled = True
        await interaction.message.edit(view=self) # Editar el mensaje para deshabilitar el botón

        # Notificar en el ticket que ha sido reclamado
        claim_embed = discord.Embed(
            title="Ticket Reclamado",
            description=f"🙋‍♂️ Este ticket ha sido reclamado por {interaction.user.mention}.",
            color=discord.Color.green()
        )
        claim_embed.set_footer(text=f"ID del Staff: {interaction.user.id}")
        await interaction.channel.send(embed=claim_embed) # Mensaje público en el ticket
        
        await cog.send_ticket_log(
            interaction.guild,
            "🙋‍♂️ Ticket Reclamado",
            f"El ticket {interaction.channel.mention} ha sido reclamado por {interaction.user.mention}.",
            interaction.user,
            "Reclamo",
            discord.Color.green(),
            interaction.channel
        )


# Clase para el menú desplegable de selección de tickets (AHORA ABRE EL TICKET DIRECTAMENTE)
class TicketTypeSelect(ui.Select):
    def __init__(self, ticket_types_config):
        options = []
        for ticket_type_name, config in ticket_types_config.items():
            options.append(discord.SelectOption(
                label=ticket_type_name,
                description=config.get("description", f"Abrir ticket para {ticket_type_name}"),
                emoji=config.get("emoji"),
                value=ticket_type_name
            ))

        super().__init__(
            placeholder="Selecciona el tipo de ticket para abrirlo...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="ticket_type_select"
        )

    async def callback(self, interaction: discord.Interaction):
        # Deferir la interacción inmediatamente para evitar "La interacción ha fallado"
        await interaction.response.defer(ephemeral=True)

        cog = self.view.bot.get_cog("Tickets") # Acceder al bot a través de la vista
        if not cog:
            return await interaction.followup.send("❌ Error interno: El módulo de tickets no está cargado.", ephemeral=True)

        selected_type = self.values[0]
        ticket_type_config = self.view.ticket_types_config.get(selected_type)

        if not ticket_type_config:
            return await interaction.followup.send("❌ Error: Tipo de ticket seleccionado no encontrado. Por favor, contacta a un administrador.", ephemeral=True)

        try:
            # Llama a la lógica de creación de ticket directamente
            await cog.create_ticket_channel(interaction, selected_type, ticket_type_config)
            
            # Resetear el select para que el usuario pueda abrir otro ticket
            self.placeholder = "Selecciona el tipo de ticket para abrirlo..."
            self.disabled = False # Asegúrate de que no se deshabilite accidentalmente
            for opt in self.options:
                opt.default = False # Desmarcar cualquier opción por defecto
            
            # Editar el mensaje para "resetear" el select
            # IMPORTANTE: Si quieres que el menú esté "listo para otra selección", debes enviar un nuevo mensaje o editar el actual
            # para que el Select menu no muestre la selección anterior como fija.
            # Una forma simple es editar el mensaje principal (el panel) para resetear el select:
            await interaction.message.edit(view=TicketPanel(self.view.bot, self.view.ticket_types_config)) # Envía una nueva instancia de la vista para "resetear"
            # Si esto causa problemas, otra opción es hacer un seguimiento de interacciones y solo dejar una selección activa.
            # Por simplicidad, volvemos a enviar la vista para que el select se vea como nuevo.

        except Exception as e:
            print(f"Error al abrir ticket desde el select menu: {e}")
            await interaction.followup.send(f"❌ Ocurrió un error al abrir el ticket: {e}", ephemeral=True)


# Clase principal para el panel de tickets (el mensaje con solo el menú)
class TicketPanel(ui.View):
    def __init__(self, bot, ticket_types_config):
        super().__init__(timeout=None) 
        self.bot = bot
        self.ticket_types_config = ticket_types_config

        # Añadir el menú desplegable
        self.add_item(TicketTypeSelect(ticket_types_config))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("Este comando solo puede ser usado en un servidor.", ephemeral=True)
            return False
        return True


# Clase para el sistema de calificación EN EL CANAL del ticket
class TicketRatingViewInChannel(ui.View):
    def __init__(self, bot, ticket_creator_id, original_guild_id):
        super().__init__(timeout=300) # 5 minutos para calificar
        self.bot = bot
        self.ticket_creator_id = ticket_creator_id
        self.original_guild_id = original_guild_id # Para acceder a la configuración del guild
        self.rating = None
        self.rated = asyncio.Event() # Evento para indicar si se ha calificado

        # Botones de calificación
        for i in range(1, 6):
            self.add_item(ui.Button(label=str(i), style=discord.ButtonStyle.blurple, custom_id=f"rating_in_channel_{i}"))
        
        # Botón para cancelar valoración (solo staff)
        self.add_item(ui.Button(label="Cancelar Valoración y Cerrar", style=discord.ButtonStyle.grey, emoji="✖️", custom_id="cancel_rating_close_ticket"))

    async def on_timeout(self):
        # Deshabilitar todos los botones si el tiempo expira
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True
        try:
            # Editar el mensaje original para deshabilitar los botones
            await self.message.edit(content="El tiempo para calificar ha expirado. El ticket no se cerrará automáticamente.", view=self)
        except discord.NotFound:
            pass # El mensaje ya pudo haber sido eliminado
        finally:
            self.rated.set() # Marcar como completado para liberar la espera, incluso si no se calificó

    # Botones de calificación (decoradores para los custom_id definidos en el init)
    @ui.button(label="1", style=discord.ButtonStyle.blurple, custom_id="rating_in_channel_1")
    @ui.button(label="2", style=discord.ButtonStyle.blurple, custom_id="rating_in_channel_2")
    @ui.button(label="3", style=discord.ButtonStyle.blurple, custom_id="rating_in_channel_3")
    @ui.button(label="4", style=discord.ButtonStyle.blurple, custom_id="rating_in_channel_4")
    @ui.button(label="5", style=discord.ButtonStyle.blurple, custom_id="rating_in_channel_5")
    async def rating_button_callback(self, interaction: discord.Interaction, button: ui.Button):
        # Asegurarse de que solo el creador del ticket pueda calificar
        if interaction.user.id != self.ticket_creator_id:
            await interaction.response.send_message("❌ Solo el creador de este ticket puede calificar.", ephemeral=True)
            return

        self.rating = int(button.label)
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True # Deshabilitar todos los botones después de una selección

        # Pedir un comentario opcional
        class RatingCommentModal(ui.Modal, title=f"Calificación de Ticket: {self.rating}/5"):
            comment_input = ui.TextInput(
                label="Tu comentario (opcional)",
                style=discord.TextStyle.paragraph,
                placeholder="¡Gracias por tu ayuda!",
                required=False,
                max_length=500
            )

            async def on_submit(self, modal_interaction: discord.Interaction):
                comment = self.comment_input.value if self.comment_input.value else "Sin comentario."
                await modal_interaction.response.defer(ephemeral=True)

                cog = self.view.bot.get_cog("Tickets")
                if cog:
                    try:
                        # Log la calificación en el canal de logs de valoración
                        # El canal del ticket actual es interaction.channel
                        await cog.log_ticket_rating(
                            modal_interaction.user,
                            self.view.rating,
                            comment,
                            interaction.channel.id, # ID del canal actual
                            self.view.ticket_creator_id,
                            interaction.guild
                        )
                        await modal_interaction.followup.send("✅ ¡Gracias por tu valoración! Tu opinión es importante.", ephemeral=True)
                        
                        # Editar el mensaje de calificación en el canal para mostrar que ya se calificó
                        await modal_interaction.message.edit(content=f"Gracias por calificar el ticket con **{self.view.rating}/5**. Comentario: '{comment}'", view=self.view)
                        
                        # Cerrar el ticket después de la calificación
                        await cog.handle_ticket_close_final(interaction.channel, modal_interaction.user, reason=f"Cerrado después de valoración ({self.view.rating}/5)")

                    except Exception as e:
                        print(f"Error al registrar valoración y cerrar ticket: {e}")
                        await modal_interaction.followup.send(f"❌ Ocurrió un error al procesar la valoración o cerrar el ticket: {e}", ephemeral=True)
                else:
                    await modal_interaction.followup.send("❌ Error interno al registrar la valoración.", ephemeral=True)
                
                self.view.stop() # Detener la vista y el timeout
                self.view.rated.set() # Marcar como completado

        modal = RatingCommentModal()
        modal.view = self
        await interaction.response.send_modal(modal)

    @ui.button(label="Cancelar Valoración y Cerrar", style=discord.ButtonStyle.grey, emoji="✖️", custom_id="cancel_rating_close_ticket")
    async def cancel_rating_close_ticket_callback(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)

        cog = self.bot.get_cog("Tickets")
        if not cog:
            return await interaction.followup.send("❌ Error interno: El módulo de tickets no está cargado.", ephemeral=True)
        
        # Solo el staff puede presionar este botón
        settings = await cog.get_ticket_settings(interaction.guild_id)
        support_role_id = settings.get("support_role_id")
        is_support_member = False
        if support_role_id:
            support_role = interaction.guild.get_role(support_role_id)
            if support_role and support_role in interaction.user.roles:
                is_support_member = True
        
        if not (is_support_member or interaction.user.guild_permissions.manage_channels):
            return await interaction.followup.send("❌ Solo el personal de soporte o un administrador pueden cancelar la valoración.", ephemeral=True)

        # Deshabilitar todos los botones
        for item in self.children:
            if isinstance(item, ui.Button):
                item.disabled = True
        await interaction.message.edit(view=self)

        await interaction.followup.send("Valoración cancelada. El ticket será cerrado.", ephemeral=True)
        
        # Cerrar el ticket sin valoración
        try:
            await cog.handle_ticket_close_final(interaction.channel, interaction.user, reason="Valoración cancelada por el staff.")
        except Exception as e:
            print(f"Error al cerrar ticket desde cancelar valoración: {e}")
            await interaction.followup.send(f"❌ Ocurrió un error al cerrar el ticket: {e}", ephemeral=True)
        
        self.stop() # Detener la vista y el timeout
        self.rated.set() # Marcar como completado

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Persistir las vistas
        # Para TicketPanel, la configuración ticket_types_config se cargará dinámicamente en on_ready o cuando se envía el panel
        # Por ahora, pasamos un diccionario vacío al registrar la vista.
        self.bot.add_view(TicketPanel(self.bot, {})) 
        self.bot.add_view(ClaimTicketButton(self.bot))
        # Para TicketRatingViewInChannel, ticket_creator_id y original_guild_id se pasarán dinámicamente.
        # Aquí pasamos 0 para los IDs al registrar la vista.
        self.bot.add_view(TicketRatingViewInChannel(self.bot, 0, 0))


    async def get_ticket_settings(self, guild_id):
        """Obtiene la configuración de tickets para un servidor desde la base de datos."""
        if self.bot.db is None:
            print("Error: La base de datos no está conectada para obtener configuración de tickets.")
            return {}
        settings = await self.bot.db.ticket_settings.find_one({"_id": guild_id})
        if settings:
            if "ticket_types" not in settings:
                settings["ticket_types"] = {}
            return settings
        return {
            "ticket_category_id": None,
            "ticket_log_channel_id": None,
            "ticket_rating_log_channel_id": None,
            "support_role_id": None,
            "ticket_types": {} 
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

    async def log_ticket_rating(self, user: discord.User, rating: int, comment: str, original_channel_id: int, ticket_creator_id: int, guild: discord.Guild):
        """Registra la valoración de un ticket en el canal de logs de valoraciones."""
        settings = await self.get_ticket_settings(guild.id)
        rating_log_channel_id = settings.get("ticket_rating_log_channel_id")
        rating_log_channel = guild.get_channel(rating_log_channel_id) if rating_log_channel_id else None

        if rating_log_channel:
            rating_embed = discord.Embed(
                title=f"⭐ Nueva Valoración de Ticket ({rating}/5)",
                description=f"El usuario {user.mention} ({user.id}) ha calificado un ticket.",
                color=discord.Color.gold() if rating >= 4 else discord.Color.orange() if rating >= 2 else discord.Color.red()
            )
            rating_embed.add_field(name="Calificación", value=f"{'⭐' * rating} ({rating}/5)", inline=False)
            rating_embed.add_field(name="Comentario", value=comment, inline=False)
            rating_embed.add_field(name="Creador del Ticket", value=f"<@{ticket_creator_id}> (ID: {ticket_creator_id})", inline=True)
            rating_embed.add_field(name="Canal Original", value=f"`#{original_channel_id}`", inline=True) 
            rating_embed.set_footer(text=f"Valorado por: {user.name} en {guild.name}")
            rating_embed.timestamp = discord.utils.utcnow()

            try:
                await rating_log_channel.send(embed=rating_embed)
            except discord.Forbidden:
                print(f"ERROR: El bot no tiene permisos para enviar logs en el canal de valoración {rating_log_channel.name} ({rating_log_channel.id}).")
            except Exception as e:
                print(f"ERROR al enviar log de valoración de tickets: {e}")
        else:
            print(f"TICKET_RATING: {user.name} - {rating}/5 | Comentario: {comment} | Guild: {guild.name}")

    async def create_ticket_channel(self, interaction: discord.Interaction, ticket_type_name: str, ticket_type_config: dict):
        guild = interaction.guild
        user = interaction.user

        category_id = ticket_type_config.get("category_id") 
        if not category_id:
            settings = await self.get_ticket_settings(guild.id)
            category_id = settings.get("ticket_category_id")
            if not category_id:
                await interaction.followup.send(f"❌ La categoría de tickets para '{ticket_type_name}' no está configurada y no hay categoría general. Pídele a un administrador que configure la categoría específica o la general del sistema de tickets.", ephemeral=True)
                return

        category = guild.get_channel(category_id)
        if not category:
            await interaction.followup.send(f"❌ La categoría '{category_id}' configurada para '{ticket_type_name}' no existe. Por favor, pídale a un administrador que la reconfigure.", ephemeral=True)
            return

        all_ticket_categories = [c for c in guild.categories if c.name.lower().startswith(DEFAULT_TICKET_CATEGORY_NAME.lower()) or c.id == category_id]
        
        user_ticket_channels = [
            channel for cat in all_ticket_categories for channel in cat.channels 
            if channel.name.startswith(DEFAULT_TICKET_CHANNEL_PREFIX) and user.id in [m.id for m in channel.members]
        ]

        if user_ticket_channels:
            return await interaction.followup.send(f"⚠️ Ya tienes un ticket abierto en {user_ticket_channels[0].mention}. Por favor, ciérralo antes de abrir uno nuevo.", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True),
            self.bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True, manage_channels=True)
        }

        settings = await self.get_ticket_settings(guild.id)
        support_role_id = settings.get("support_role_id")
        support_role = None
        if support_role_id:
            support_role = guild.get_role(support_role_id)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True)
            else:
                await interaction.followup.send(f"⚠️ El rol de soporte configurado no existe. Los miembros de soporte no podrán ver el ticket a menos que el rol sea reconfigurado.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ No hay un rol de soporte configurado. Asegúrate de que un administrador use `/setsupportrole` para que el personal de soporte pueda ver los tickets.", ephemeral=True)

        ticket_channel_name = f"{DEFAULT_TICKET_CHANNEL_PREFIX}{user.name.replace(' ', '-').lower()}-{user.discriminator if hasattr(user, 'discriminator') else user.id}"[:100]

        try:
            ticket_channel = await guild.create_text_channel(
                ticket_channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket '{ticket_type_name}' abierto por {user.name}"
            )
            await interaction.followup.send(f"✅ Tu ticket '{ticket_type_name}' ha sido creado: {ticket_channel.mention}", ephemeral=True)

            ticket_embed = discord.Embed(
                title=f"🎫 Ticket de {user.display_name} - Tipo: {ticket_type_name}",
                description=f"**Usuario:** {user.mention}\n**ID:** `{user.id}`\n\nHola {user.mention},\nUn miembro del equipo de soporte te atenderá en breve. Por favor, describe tu problema con el mayor detalle posible.",
                color=discord.Color.blue()
            )
            ticket_embed.set_footer(text="Gracias por tu paciencia.")
            ticket_embed.timestamp = discord.utils.utcnow()

            # Añadir solo el botón de reclamar ticket
            view = ClaimTicketButton(self.bot)
            
            await ticket_channel.send(f"{user.mention}" + (f" {support_role.mention}" if support_role else ""), embed=ticket_embed, view=view)
            
            await self.send_ticket_log(
                guild,
                f"🎫 Ticket Abierto - {ticket_type_name}",
                f"**Usuario:** {user.mention} ha abierto un ticket de tipo '{ticket_type_name}'.",
                user,
                "Apertura",
                discord.Color.blue(),
                ticket_channel
            )

        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos para crear canales o configurar los permisos necesarios. Asegúrate de que mi rol tenga `Gestionar Canales` y esté por encima de los roles de los usuarios en la jerarquía.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al abrir el ticket: {e}", ephemeral=True)
            print(f"Error al abrir ticket: {e}")

    # --- Flujo de Cierre de Ticket (Inicia la valoración) ---
    async def handle_ticket_close_initiate_rating(self, ticket_channel: discord.TextChannel, ticket_creator_id: int, closed_by: discord.Member):
        guild = ticket_channel.guild
        ticket_creator = guild.get_member(ticket_creator_id) or await self.bot.fetch_user(ticket_creator_id) 
        
        # Enviar mensaje de valoración en el canal del ticket
        rating_embed = discord.Embed(
            title="🌟 ¡Valora tu Experiencia con el Ticket!",
            description=f"Hola {ticket_creator.mention if ticket_creator else 'creador del ticket'},\nPor favor, tómate un momento para calificar tu experiencia con este ticket.\n\n**¿Qué tan satisfecho estás con el soporte recibido?** (1 = Muy insatisfecho, 5 = Muy satisfecho)",
            color=discord.Color.gold()
        )
        rating_embed.set_footer(text="Haz clic en un número para calificar, o 'Cancelar Valoración' si eres Staff.")
        
        # Pasar el ID del creador y el guild_id a la vista de valoración en el canal
        rating_view = TicketRatingViewInChannel(self.bot, ticket_creator_id, guild.id)
        
        try:
            # Enviar la vista y esperar a que se complete la valoración
            rating_message = await ticket_channel.send(embed=rating_embed, view=rating_view)
            rating_view.message = rating_message # Guardar el mensaje para poder editarlo después

            # Esperar a que la valoración se complete (o se cancele)
            await rating_view.rated.wait()

        except Exception as e:
            print(f"Error al iniciar valoración en el canal: {e}")
            await ticket_channel.send(f"❌ Ocurrió un error al iniciar el proceso de valoración: {e}")
            # Si hay un error aquí, el ticket podría quedar abierto.
            # Podríamos añadir una llamada a handle_ticket_close_final aquí también para asegurarnos el cierre.

    # --- Cierre Final del Ticket (Después de valoración o cancelación) ---
    async def handle_ticket_close_final(self, ticket_channel: discord.TextChannel, closed_by: discord.Member, reason: str):
        guild = ticket_channel.guild
        
        # Intentar obtener el ID del creador del nombre del canal para el log
        ticket_creator_id = None
        try:
            parts = ticket_channel.name.split('-')
            if len(parts) > 1 and parts[-1].isdigit():
                ticket_creator_id = int(parts[-1])
        except ValueError:
            pass
        ticket_creator = guild.get_member(ticket_creator_id) if ticket_creator_id else None

        await ticket_channel.send("El ticket se cerrará en 5 segundos...")
        await asyncio.sleep(5)

        await self.send_ticket_log(
            guild,
            "✅ Ticket Cerrado",
            f"El ticket {ticket_channel.name} ha sido cerrado.",
            ticket_creator if ticket_creator else closed_by, 
            "Cierre",
            discord.Color.green(),
            ticket_channel,
            closed_by,
            reason
        )

        try:
            await ticket_channel.delete(reason=f"Ticket cerrado por {closed_by.name}: {reason}")
            print(f"Canal de ticket {ticket_channel.name} ({ticket_channel.id}) eliminado.")
        except discord.Forbidden:
            print("❌ No tengo los permisos para eliminar canales. Asegúrate de que mi rol tenga `Gestionar Canales` y esté por encima de la categoría de tickets.")
            try:
                await ticket_channel.send("❌ No pude eliminar este canal debido a falta de permisos.")
            except:
                pass
        except Exception as e:
            print(f"❌ Ocurrió un error al cerrar el ticket (final): {e}")


    # --- Comandos de Configuración de Tickets (Slash Commands) ---

    @app_commands.command(name="setticketcategory", description="Configura la categoría por defecto donde se crearán los tickets.")
    @app_commands.describe(category="La categoría donde se crearán los tickets por defecto.")
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
            await interaction.followup.send(f"✅ ¡La categoría **por defecto** para tickets se ha configurado a `{category.name}` con éxito!.", ephemeral=True)
            print(f"Categoría de tickets por defecto configurada a {category.name} ({category.id}) para el servidor '{interaction.guild.name}'.")
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al configurar la categoría: {e}", ephemeral=True)
            print(f"Error al configurar la categoría de tickets: {e}")

    @app_commands.command(name="setticketlogs", description="Configura el canal para los logs de apertura/cierre de tickets.")
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

    @app_commands.command(name="setratinglogs", description="Configura el canal para los logs de valoración de tickets.")
    @app_commands.describe(channel="El canal de texto para los logs de valoración de tickets.")
    @app_commands.default_permissions(manage_channels=True)
    async def set_ticket_rating_logs_slash(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)

        try:
            await self.bot.db.ticket_settings.update_one(
                {"_id": interaction.guild_id},
                {"$set": {"ticket_rating_log_channel_id": channel.id}},
                upsert=True
            )
            await interaction.followup.send(f"✅ ¡El canal de logs de **valoración** de tickets se ha configurado a {channel.mention} con éxito!", ephemeral=True)
            print(f"Canal de logs de valoración de tickets configurado a {channel.name} ({channel.id}) para el servidor '{interaction.guild.name}'.")
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al configurar el canal de logs de valoración: {e}", ephemeral=True)
            print(f"Error al configurar el canal de logs de valoración: {e}")

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
            
    # --- Comandos para Tipos de Tickets Personalizados ---
    @app_commands.command(name="addtickettype", description="Añade un nuevo tipo de ticket con su categoría de destino y emoji.")
    @app_commands.describe(
        name="Nombre del tipo de ticket (ej. Soporte General)",
        category="Categoría de canal donde se abrirán estos tickets.",
        emoji="Emoji para este tipo de ticket (opcional).",
        description="Breve descripción para el menú (opcional)."
    )
    @app_commands.default_permissions(manage_channels=True)
    async def add_ticket_type_slash(self, interaction: discord.Interaction, name: str, category: discord.CategoryChannel, emoji: str = None, description: str = None):
        await interaction.response.defer(ephemeral=True)
        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)

        guild_id = interaction.guild_id
        
        if emoji:
            if not (emoji.startswith('<:') and emoji.endswith('>') or emoji.startswith('<a:') and emoji.endswith('>')) and len(emoji) > 2:
                pass
            elif not discord.utils.get(self.bot.emojis, name=emoji[2:-1].split(':')[0]):
                return await interaction.followup.send(f"❌ El emoji `{emoji}` no es un emoji de Discord válido al que tenga acceso el bot. Si es un emoji personalizado, asegúrate de que el bot esté en un servidor donde ese emoji exista. Para emojis normales de unicode, puedes copiarlos directamente (ej. `❓`).", ephemeral=True)

        try:
            await self.bot.db.ticket_settings.update_one(
                {"_id": guild_id},
                {"$set": {
                    f"ticket_types.{name}": {
                        "category_id": category.id,
                        "emoji": emoji,
                        "description": description
                    }
                }},
                upsert=True
            )
            await interaction.followup.send(f"✅ Tipo de ticket `{name}` configurado para usar la categoría `{category.name}`.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al añadir el tipo de ticket: {e}", ephemeral=True)
            print(f"Error al añadir tipo de ticket: {e}")

    @app_commands.command(name="removetickettype", description="Elimina un tipo de ticket existente.")
    @app_commands.describe(name="Nombre del tipo de ticket a eliminar.")
    @app_commands.default_permissions(manage_channels=True)
    async def remove_ticket_type_slash(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)

        guild_id = interaction.guild_id
        
        result = await self.bot.db.ticket_settings.update_one(
            {"_id": guild_id},
            {"$unset": {f"ticket_types.{name}": ""}}
        )

        if result.modified_count > 0:
            await interaction.followup.send(f"✅ Tipo de ticket `{name}` eliminado correctamente.", ephemeral=True)
        else:
            await interaction.followup.send(f"⚠️ No se encontró el tipo de ticket `{name}`.", ephemeral=True)


    @app_commands.command(name="listtickettypes", description="Lista todos los tipos de tickets configurados.")
    @app_commands.default_permissions(manage_channels=True)
    async def list_ticket_types_slash(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)

        guild_id = interaction.guild_id
        settings = await self.get_ticket_settings(guild_id)
        ticket_types = settings.get("ticket_types", {})

        if not ticket_types:
            return await interaction.followup.send("ℹ️ No hay tipos de tickets personalizados configurados. Usa `/addtickettype` para añadir uno.", ephemeral=True)

        description = "Tipos de tickets configurados:\n\n"
        for name, config in ticket_types.items():
            category = interaction.guild.get_channel(config["category_id"])
            category_name = category.name if category else "Categoría desconocida"
            emoji = config.get("emoji", "")
            desc = config.get("description", "")
            description += f"{emoji} **{name}**\n  - Categoría: `{category_name}`\n  - Descripción: `{desc}`\n\n"
        
        embed = discord.Embed(
            title="🎫 Tipos de Tickets Personalizados",
            description=description,
            color=discord.Color.purple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


    # --- Comando para enviar el panel de tickets ---
    @app_commands.command(name="sendticketpanel", description="Envía el mensaje del panel de tickets interactivo a un canal.")
    @app_commands.describe(channel="El canal donde se enviará el panel de tickets.", title="Título para el embed del panel (opcional).", description="Descripción para el embed del panel (opcional).")
    @app_commands.default_permissions(manage_channels=True)
    async def send_ticket_panel_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str = "Sistema de Tickets", description: str = "Selecciona el tipo de soporte que necesitas y abre un ticket."):
        await interaction.response.defer(ephemeral=True)

        if self.bot.db is None:
            return await interaction.followup.send("❌ Error: La base de datos no está conectada.", ephemeral=True)
        
        settings = await self.get_ticket_settings(interaction.guild_id)
        ticket_types_config = settings.get("ticket_types", {})

        if not ticket_types_config:
            return await interaction.followup.send("❌ No hay tipos de tickets personalizados configurados. Usa `/addtickettype` para configurar al menos uno antes de enviar el panel.", ephemeral=True)

        panel_embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blurple()
        )
        panel_embed.set_footer(text="¡Selecciona una opción para abrir un ticket!")

        view = TicketPanel(self.bot, ticket_types_config)
        
        try:
            await channel.send(embed=panel_embed, view=view)
            await interaction.followup.send(f"✅ ¡Panel de tickets enviado a {channel.mention}!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send(f"❌ No tengo permisos para enviar mensajes en {channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al enviar el panel: {e}", ephemeral=True)
            print(f"Error al enviar el panel de tickets: {e}")

    # --- Comandos para Gestión de Tickets (Adaptado) ---

    @app_commands.command(name="close", description="Cierra el ticket actual (inicia el proceso de valoración).")
    @app_commands.describe(reason="La razón por la que se cierra el ticket (opcional).")
    async def close_ticket_slash(self, interaction: discord.Interaction, reason: str = "Sin razón especificada."):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            return await interaction.followup.send("Este comando solo puede ser usado en un servidor.", ephemeral=True)

        if not interaction.channel.name.startswith(DEFAULT_TICKET_CHANNEL_PREFIX):
            return await interaction.followup.send("❌ Este comando solo puede usarse dentro de un canal de ticket.", ephemeral=True)
        
        creator_id = None
        try:
            parts = interaction.channel.name.split('-')
            if len(parts) > 1 and parts[-1].isdigit():
                creator_id = int(parts[-1])
        except ValueError:
            pass
        
        is_ticket_creator = (creator_id == interaction.user.id)
        
        settings = await self.get_ticket_settings(interaction.guild_id)
        support_role_id = settings.get("support_role_id")
        is_support_member = False
        if support_role_id:
            support_role = interaction.guild.get_role(support_role_id)
            if support_role and support_role in interaction.user.roles:
                is_support_member = True

        if not (is_ticket_creator or is_support_member or interaction.user.guild_permissions.manage_channels):
            return await interaction.followup.send("❌ Solo el creador del ticket, un miembro de soporte o un administrador pueden iniciar el cierre de este ticket.", ephemeral=True)

        await interaction.followup.send(f"✅ Proceso de cierre iniciado. El mensaje de valoración aparecerá en este canal.", ephemeral=True)
        
        # Iniciar el proceso de valoración en el canal
        try:
            await self.handle_ticket_close_initiate_rating(interaction.channel, creator_id, interaction.user)
        except Exception as e:
            print(f"Error al iniciar valoración desde /close command: {e}")
            await interaction.followup.send(f"❌ Ocurrió un error al iniciar la valoración: {e}", ephemeral=True)


# Función de configuración del Cog
async def setup(bot):
    await bot.add_cog(Tickets(bot))