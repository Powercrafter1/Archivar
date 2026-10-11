package net.archivar;

import net.archivar.block.StorageInterfaceBlock;
import net.archivar.block.StorageInterfaceBlockEntity;
import net.archivar.network.ArchivarPayloads;
import net.archivar.storage.ArchivarData;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.itemgroup.v1.ItemGroupEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.core.NonNullList;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.CreativeModeTabs;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.*;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockBehaviour;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public class Archivar implements ModInitializer {
    public static final String MOD_ID = "archivar";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    public static ResourceLocation id(String path) {
        return ResourceLocation.fromNamespaceAndPath(MOD_ID, path);
    }

    public static final Block STORAGE_INTERFACE = new StorageInterfaceBlock(
            BlockBehaviour.Properties.ofFullCopy(Blocks.IRON_BLOCK).noOcclusion()
    );
    public static final BlockItem STORAGE_INTERFACE_ITEM = new BlockItem(STORAGE_INTERFACE, new Item.Properties());
    public static BlockEntityType<StorageInterfaceBlockEntity> STORAGE_INTERFACE_BE;

    @Override
    public void onInitialize() {
        Registry.register(BuiltInRegistries.BLOCK, id("storage_interface"), STORAGE_INTERFACE);
        Registry.register(BuiltInRegistries.ITEM, id("storage_interface"), STORAGE_INTERFACE_ITEM);

        STORAGE_INTERFACE_BE = Registry.register(
                BuiltInRegistries.BLOCK_ENTITY_TYPE,
                id("storage_interface"),
                BlockEntityType.Builder.of(StorageInterfaceBlockEntity::new, STORAGE_INTERFACE).build()
        );

        ItemGroupEvents.modifyEntriesEvent(CreativeModeTabs.FUNCTIONAL_BLOCKS).register(entries -> {
            entries.accept(STORAGE_INTERFACE_ITEM);
        });

        // Payloads
        PayloadTypeRegistry.playS2C().register(ArchivarPayloads.SyncTerminalPayload.TYPE, ArchivarPayloads.SyncTerminalPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.RequestOpenTerminalPayload.TYPE, ArchivarPayloads.RequestOpenTerminalPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.ExtractItemPayload.TYPE, ArchivarPayloads.ExtractItemPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.InsertItemPayload.TYPE, ArchivarPayloads.InsertItemPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.ClickCraftSlotPayload.TYPE, ArchivarPayloads.ClickCraftSlotPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.TakeCraftResultPayload.TYPE, ArchivarPayloads.TakeCraftResultPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.ClearCraftGridPayload.TYPE, ArchivarPayloads.ClearCraftGridPayload.STREAM_CODEC);

        // Terminal Öffnen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.RequestOpenTerminalPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> syncAndOpenTerminal(context.player()));
        });

        // Item Entnehmen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.ExtractItemPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                ItemStack extracted = vault.extract(payload.sample(), payload.amount());
                if (!extracted.isEmpty()) {
                    if (!sp.getInventory().add(extracted)) {
                        sp.drop(extracted, false);
                    }
                    syncAndOpenTerminal(sp);
                }
            });
        });

        // Item Einzahlen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.InsertItemPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                if (payload.slotIndex() >= 0 && payload.slotIndex() < sp.getInventory().items.size()) {
                    ItemStack inSlot = sp.getInventory().items.get(payload.slotIndex());
                    if (!inSlot.isEmpty()) {
                        ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                        vault.insert(inSlot.copy());
                        inSlot.setCount(0);
                        syncAndOpenTerminal(sp);
                    }
                }
            });
        });

        // Klick auf Crafting-Slot (Zutaten setzen/herausnehmen)
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.ClickCraftSlotPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                int slot = payload.slotIndex();
                if (slot >= 0 && slot < 9) {
                    ItemStack inSlot = vault.craftingGrid.get(slot);
                    if (payload.shift()) {
                        // Shift-Klick: Zutat direkt zurück ins Archiv
                        if (!inSlot.isEmpty()) {
                            vault.insert(inSlot.copy());
                            vault.craftingGrid.set(slot, ItemStack.EMPTY);
                        }
                    } else if (payload.button() == 1) {
                        // Rechtsklick: 1 Item entnehmen und ins Inventar
                        if (!inSlot.isEmpty()) {
                            ItemStack taken = inSlot.split(1);
                            if (!sp.getInventory().add(taken)) {
                                sp.drop(taken, false);
                            }
                            if (inSlot.isEmpty()) {
                                vault.craftingGrid.set(slot, ItemStack.EMPTY);
                            }
                        }
                    } else {
                        // Linksklick: Ganzen Slot ins Inventar nehmen
                        if (!inSlot.isEmpty()) {
                            if (!sp.getInventory().add(inSlot.copy())) {
                                sp.drop(inSlot, false);
                            }
                            vault.craftingGrid.set(slot, ItemStack.EMPTY);
                        }
                    }
                    syncAndOpenTerminal(sp);
                }
            });
        });

        // Crafting-Ergebnis herstellen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.TakeCraftResultPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);

                do {
                    CraftingInput input = CraftingInput.of(3, 3, vault.craftingGrid);
                    Optional<RecipeHolder<CraftingRecipe>> match = sp.server.getRecipeManager()
                            .getRecipeFor(RecipeType.CRAFTING, input, sp.serverLevel());

                    if (match.isEmpty()) break;

                    ItemStack result = match.get().value().assemble(input, sp.server.registryAccess());
                    if (result.isEmpty()) break;

                    // Platz im Spielerinventar prüfen
                    if (!sp.getInventory().canPlaceItem(0, result) && sp.getInventory().getFreeSlot() == -1) {
                        break;
                    }

                    // 1 Zutat aus jedem belegten Slot abziehen
                    NonNullList<ItemStack> remaining = match.get().value().getRemainingItems(input);
                    for (int i = 0; i < 9; i++) {
                        ItemStack current = vault.craftingGrid.get(i);
                        if (!current.isEmpty()) {
                            current.shrink(1);
                        }
                        if (!remaining.get(i).isEmpty()) {
                            if (current.isEmpty()) {
                                vault.craftingGrid.set(i, remaining.get(i));
                            } else {
                                vault.insert(remaining.get(i));
                            }
                        }
                    }

                    if (!sp.getInventory().add(result)) {
                        sp.drop(result, false);
                    }

                } while (payload.shift()); // Wenn Shift: Solange craften, wie Zutaten da sind!

                syncAndOpenTerminal(sp);
            });
        });

        // Crafting-Gitter leeren
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.ClearCraftGridPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                for (int i = 0; i < 9; i++) {
                    ItemStack stack = vault.craftingGrid.get(i);
                    if (!stack.isEmpty()) {
                        vault.insert(stack.copy());
                        vault.craftingGrid.set(i, ItemStack.EMPTY);
                    }
                }
                syncAndOpenTerminal(sp);
            });
        });

        LOGGER.info("Archivar Lagermod mit AE2-Crafting geladen!");
    }

    public static void syncAndOpenTerminal(ServerPlayer player) {
        ArchivarData.Vault vault = ArchivarData.get(player.server).getVault(player);
        List<ArchivarPayloads.ItemEntry> entries = vault.getAll().stream()
                .map(e -> new ArchivarPayloads.ItemEntry(e.template, e.count))
                .toList();
        List<ItemStack> craftGrid = new ArrayList<>(vault.craftingGrid);
        ServerPlayNetworking.send(player, new ArchivarPayloads.SyncTerminalPayload(entries, craftGrid));
    }
}
