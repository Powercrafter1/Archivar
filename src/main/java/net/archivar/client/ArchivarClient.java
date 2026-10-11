package net.archivar.client;

import com.mojang.blaze3d.platform.InputConstants;
import net.archivar.network.ArchivarPayloads;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import org.lwjgl.glfw.GLFW;

public class ArchivarClient implements ClientModInitializer {
    public static KeyMapping openTerminalKey;

    @Override
    public void onInitializeClient() {
        openTerminalKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
                "key.archivar.open_terminal",
                InputConstants.Type.KEYSYM,
                GLFW.GLFW_KEY_K,
                "category.archivar.general"
        ));

        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            while (openTerminalKey.consumeClick()) {
                if (client.player != null) {
                    ClientPlayNetworking.send(new ArchivarPayloads.RequestOpenTerminalPayload());
                }
            }
        });

        ClientPlayNetworking.registerGlobalReceiver(ArchivarPayloads.SyncTerminalPayload.TYPE, (payload, context) -> {
            context.client().execute(() -> {
                Minecraft mc = Minecraft.getInstance();
                if (mc.screen instanceof ArchivarTerminalScreen current) {
                    current.updateData(payload.items(), payload.craftGrid());
                } else {
                    mc.setScreen(new ArchivarTerminalScreen(payload.items(), payload.craftGrid()));
                }
            });
        });
    }
}
