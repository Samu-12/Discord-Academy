import discord
from discord.ext import commands

# Definimos una clase que hereda de commands.Cog
class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- Posible Error 1: `discord.Intents.members` no habilitado o `member.avatar` / `member.default_avatar` ---
    # Si ves un error relacionado con 'NoneType' object has no attribute 'url'
    # o si el evento on_member_join no se dispara, podría ser por los Intents.
    # Asegúrate de que `intents.members = True` y `intents.message_content = True` están en main.py
    # y habilitados en el Portal de Desarrolladores de Discord.

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """
        Este evento se activa cuando un nuevo miembro se une al servidor.
        Envía un mensaje de bienvenida personalizado en el canal configurado.
        """
        if self.bot.db is None:
            print("Error: La base de datos no está conectada para el evento on_member_join.")
            return

        guild_id = member.guild.id

        settings = await self.bot.db.welcome_settings.find_one({"_id": guild_id})

        welcome_channel_id = None
        if settings:
            welcome_channel_id = settings.get("channel_id")

        if not welcome_channel_id:
            print(f"No hay un canal de bienvenida configurado para el servidor '{member.guild.name}' ({guild_id}).")
            return

        welcome_channel = self.bot.get_channel(welcome_channel_id)

        if welcome_channel is None:
            print(f"El canal de bienvenida configurado ({welcome_channel_id}) para el servidor '{member.guild.name}' no se encontró o el bot no tiene acceso.")
            return

        member_count = len(member.guild.members)

        embed = discord.Embed(
            title=f"🎉 ¡Bienvenido a {member.guild.name}!",
            description=f"¡Hola {member.mention}! Nos alegra tenerte aquí.",
            color=0x7289DA
        )
        
        # --- Posible Error 2: La URL de la imagen de bienvenida ---
        # Si la imagen no se muestra o hay un error al cargar el embed,
        # asegúrate de que la URL sea directamente a la imagen (termina en .png, .jpg, .gif, etc.)
        # y que el bot pueda acceder a ella.
        # Por favor, reemplaza esta URL con la tuya.
        embed.set_image(url="https://i.imgur.com/your_custom_welcome_image.png") # <<-- ¡CAMBIA ESTA URL!

        # Asegurarse de usar discord.utils.utcnow() para timestamps
        embed.timestamp = discord.utils.utcnow()
        
        # --- Posible Error 3: Permisos del Bot o Error con set_thumbnail ---
        # Si el bot no tiene permisos de `Read Message History` o `View Channel`
        # en el canal de bienvenida, no podrá enviar el mensaje.
        # Si member.avatar o member.default_avatar no tienen .url por alguna razón
        # aunque es raro con discord.py, podemos añadir un fallback.
        try:
            # Intentar usar el avatar del miembro, si no, el default, si no, un string vacío para evitar AttributeError
            avatar_url = member.avatar.url if member.avatar else (member.default_avatar.url if member.default_avatar else "")
            if avatar_url: # Solo establecer si hay una URL válida
                embed.set_thumbnail(url=avatar_url)
        except Exception as e:
            print(f"Error al obtener URL del avatar para {member.name}: {e}")
            # Puedes poner una imagen por defecto si no se puede obtener el avatar del usuario
            # embed.set_thumbnail(url="URL_DE_IMAGEN_DE_AVATAR_POR_DEFECTO.png")


        embed.add_field(name="Miembros Actualmente", value=f"Somos **{member_count}** miembros en el servidor.", inline=False)
        embed.set_footer(text="¡Esperamos que disfrutes tu estancia!")
        
        try:
            await welcome_channel.send(embed=embed)
            print(f"Mensaje de bienvenida enviado para {member.name} en el servidor '{member.guild.name}'.")
        except discord.Forbidden:
            print(f"El bot no tiene permisos para enviar mensajes en el canal {welcome_channel.name} ({welcome_channel.id}) del servidor '{member.guild.name}'.")
        except Exception as e:
            print(f"Ocurrió un error al enviar el mensaje de bienvenida: {e}")

    @commands.command(name='setbienvenida')
    @commands.has_permissions(administrator=True)
    async def set_bienvenida(self, ctx, channel: discord.TextChannel):
        """
        Comando para configurar el canal de bienvenida para el servidor.
        Uso: !setbienvenida #nombre-del-canal
        """
        if self.bot.db is None:
            await ctx.send("❌ Error: La base de datos no está conectada. No se pudo configurar el canal.")
            return

        guild_id = ctx.guild.id
        channel_id = channel.id

        try:
            await self.bot.db.welcome_settings.update_one(
                {"_id": guild_id},
                {"$set": {"channel_id": channel_id}},
                upsert=True
            )
            await ctx.send(f"✅ ¡El canal de bienvenida se ha configurado a {channel.mention} con éxito!")
            print(f"Canal de bienvenida configurado a {channel.name} ({channel.id}) para el servidor '{ctx.guild.name}'.")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al configurar el canal de bienvenida: {e}")
            print(f"Error al configurar el canal de bienvenida: {e}")

async def setup(bot):
    await bot.add_cog(Welcome(bot))