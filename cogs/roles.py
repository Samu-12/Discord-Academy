import discord
from discord.ext import commands
from discord import app_commands

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- Comandos de Prefijo para Roles (sin cambios) ---

    @commands.command(name='addrole')
    @commands.has_permissions(manage_roles=True)
    async def add_role_prefix(self, ctx, member: discord.Member, *, role_name: str):
        """
        [Prefijo] Añade un rol a un miembro.
        Uso: !addrole @usuario <nombre del rol>
        """
        role = discord.utils.get(ctx.guild.roles, name=role_name)

        if not role:
            return await ctx.send(f"❌ No se encontró el rol `{role_name}`.")

        if role.position >= ctx.guild.me.top_role.position:
            return await ctx.send(f"❌ No puedo asignar el rol `{role.name}` porque está por encima o al mismo nivel que mi rol más alto.")

        if role in member.roles:
            return await ctx.send(f"⚠️ {member.mention} ya tiene el rol `{role.name}`.")

        try:
            await member.add_roles(role, reason=f"Rol asignado por {ctx.author} usando el comando !addrole.")
            await ctx.send(f"✅ Se le ha asignado el rol `{role.name}` a {member.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ No tengo los permisos necesarios para añadir este rol. Asegúrate de que mi rol esté por encima del rol que intentas asignar.")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al añadir el rol: {e}")

    @commands.command(name='removerole')
    @commands.has_permissions(manage_roles=True)
    async def remove_role_prefix(self, ctx, member: discord.Member, *, role_name: str):
        """
        [Prefijo] Quita un rol a un miembro.
        Uso: !removerole @usuario <nombre del rol>
        """
        role = discord.utils.get(ctx.guild.roles, name=role_name)

        if not role:
            return await ctx.send(f"❌ No se encontró el rol `{role_name}`.")

        if role.position >= ctx.guild.me.top_role.position:
            return await ctx.send(f"❌ No puedo quitar el rol `{role.name}` porque está por encima o al mismo nivel que mi rol más alto.")

        if role not in member.roles:
            return await ctx.send(f"⚠️ {member.mention} no tiene el rol `{role.name}`.")

        try:
            await member.remove_roles(role, reason=f"Rol removido por {ctx.author} usando el comando !removerole.")
            await ctx.send(f"✅ Se le ha quitado el rol `{role.name}` a {member.mention}.")
        except discord.Forbidden:
            await ctx.send("❌ No tengo los permisos necesarios para quitar este rol. Asegúrate de que mi rol esté por encima del rol que intentas quitar.")
        except Exception as e:
            await ctx.send(f"❌ Ocurrió un error al quitar el rol: {e}")

    # --- Comandos de Barra (Slash Commands) para Roles (Corregidos) ---

    @app_commands.command(name="addrole", description="Asigna un rol a un miembro del servidor.")
    @app_commands.describe(member="El miembro al que se le asignará el rol.", role="El rol a asignar.")
    @app_commands.default_permissions(manage_roles=True)
    async def add_role_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """
        [Barra] Asigna un rol a un miembro del servidor.
        """
        # IMPORTANTE: Deferir la interacción al principio para poder responder más tarde.
        await interaction.response.defer(ephemeral=True) # Esto "reconoce" la interacción

        # Asegúrate de que el comando se use en un servidor
        if interaction.guild is None:
            # Usa followup.send() después de deferir
            return await interaction.followup.send("Este comando solo puede ser usado en un servidor.", ephemeral=True)

        # Verificar la jerarquía de roles del bot y del rol a asignar
        if role.position >= interaction.guild.me.top_role.position:
            return await interaction.followup.send(
                f"❌ No puedo asignar el rol `{role.name}` porque está por encima o al mismo nivel que mi rol más alto. Mueve mi rol por encima del rol `{role.name}` en la jerarquía de roles del servidor.",
                ephemeral=True
            )
        # Verificar la jerarquía de roles del usuario que ejecuta el comando y del rol a asignar
        if interaction.user.top_role.position <= role.position and interaction.user.id != interaction.guild.owner_id:
             return await interaction.followup.send(
                 f"❌ No puedes asignar el rol `{role.name}` porque está por encima o al mismo nivel que tu rol más alto. Quieres gestionar roles que están por encima de ti.",
                 ephemeral=True
             )

        if role in member.roles:
            return await interaction.followup.send(f"⚠️ {member.mention} ya tiene el rol `{role.name}`.", ephemeral=True)

        try:
            await member.add_roles(role, reason=f"Rol asignado por {interaction.user} usando el comando /addrole.")
            await interaction.followup.send(f"✅ Se le ha asignado el rol `{role.name}` a {member.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos necesarios para añadir este rol. Asegúrate de que mi rol esté por encima del rol que intentas asignar.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al añadir el rol: {e}", ephemeral=True)

    @app_commands.command(name="removerole", description="Quita un rol a un miembro del servidor.")
    @app_commands.describe(member="El miembro al que se le quitará el rol.", role="El rol a quitar.")
    @app_commands.default_permissions(manage_roles=True)
    async def remove_role_slash(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role):
        """
        [Barra] Quita un rol a un miembro del servidor.
        """
        # IMPORTANTE: Deferir la interacción al principio
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            return await interaction.followup.send("Este comando solo puede ser usado en un servidor.", ephemeral=True)

        if role.position >= interaction.guild.me.top_role.position:
            return await interaction.followup.send(
                f"❌ No puedo quitar el rol `{role.name}` porque está por encima o al mismo nivel que mi rol más alto. Mueve mi rol por encima del rol `{role.name}` en la jerarquía de roles del servidor.",
                ephemeral=True
            )
        if interaction.user.top_role.position <= role.position and interaction.user.id != interaction.guild.owner_id:
            return await interaction.followup.send(
                f"❌ No puedes quitar el rol `{role.name}` porque está por encima o al mismo nivel que tu rol más alto. Quieres gestionar roles que están por encima de ti.",
                ephemeral=True
            )

        if role not in member.roles:
            return await interaction.followup.send(f"⚠️ {member.mention} no tiene el rol `{role.name}`.", ephemeral=True)

        try:
            await member.remove_roles(role, reason=f"Rol removido por {interaction.user} usando el comando /removerole.")
            await interaction.followup.send(f"✅ Se le ha quitado el rol `{role.name}` a {member.mention}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ No tengo los permisos necesarios para quitar este rol. Asegúrate de que mi rol esté por encima del rol que intentas quitar.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Ocurrió un error al quitar el rol: {e}", ephemeral=True)

# Función de configuración del Cog
async def setup(bot):
    await bot.add_cog(Roles(bot))