package net.archivar.storage;

import net.minecraft.core.HolderLookup;
import net.minecraft.core.NonNullList;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.Tag;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.ContainerHelper;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.saveddata.SavedData;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class ArchivarData extends SavedData {

    public static class Entry {
        public ItemStack template;
        public long count;

        public Entry(ItemStack template, long count) {
            this.template = template.copy();
            this.template.setCount(1);
            this.count = count;
        }
    }

    public static class Vault {
        public final List<Entry> items = new ArrayList<>();
        // Persistentes 3x3 Crafting-Gitter (bleibt beim Schließen erhalten!)
        public final NonNullList<ItemStack> craftingGrid = NonNullList.withSize(9, ItemStack.EMPTY);

        public synchronized void insert(ItemStack stack) {
            if (stack.isEmpty()) return;
            for (Entry e : items) {
                if (ItemStack.isSameItemSameComponents(e.template, stack)) {
                    e.count += stack.getCount();
                    return;
                }
            }
            items.add(new Entry(stack, stack.getCount()));
        }

        public synchronized ItemStack extract(ItemStack sample, int maxAmount) {
            for (Iterator<Entry> it = items.iterator(); it.hasNext(); ) {
                Entry e = it.next();
                if (ItemStack.isSameItemSameComponents(e.template, sample)) {
                    int toTake = (int) Math.min(e.count, maxAmount);
                    e.count -= toTake;
                    ItemStack out = e.template.copy();
                    out.setCount(toTake);
                    if (e.count <= 0) {
                        it.remove();
                    }
                    return out;
                }
            }
            return ItemStack.EMPTY;
        }

        public synchronized List<Entry> getAll() {
            return new ArrayList<>(items);
        }
    }

    private final Map<UUID, Vault> vaults = new ConcurrentHashMap<>();

    public ArchivarData() {
    }

    public static final SavedData.Factory<ArchivarData> FACTORY =
            new SavedData.Factory<>(ArchivarData::new, ArchivarData::load, null);

    public static ArchivarData get(MinecraftServer server) {
        return server.overworld().getDataStorage().computeIfAbsent(FACTORY, "archivar_storage");
    }

    public Vault getVault(ServerPlayer player) {
        UUID id = player.getUUID();
        if (player.server.isSingleplayer()) {
            id = UUID.fromString("00000000-0000-0000-0000-000000000000");
        }
        return vaults.computeIfAbsent(id, k -> new Vault());
    }

    public Vault getVault(UUID id) {
        return vaults.computeIfAbsent(id, k -> new Vault());
    }

    @Override
    public CompoundTag save(CompoundTag tag, HolderLookup.Provider registries) {
        ListTag vaultList = new ListTag();
        for (Map.Entry<UUID, Vault> en : vaults.entrySet()) {
            CompoundTag vTag = new CompoundTag();
            vTag.putUUID("owner", en.getKey());

            // 1. Archiv Items
            ListTag itemList = new ListTag();
            for (Entry entry : en.getValue().items) {
                CompoundTag itemTag = new CompoundTag();
                Tag savedItem = entry.template.saveOptional(registries);
                itemTag.put("item", savedItem);
                itemTag.putLong("count", entry.count);
                itemList.add(itemTag);
            }
            vTag.put("items", itemList);

            // 2. Crafting Grid Slots
            ContainerHelper.saveAllItems(vTag, en.getValue().craftingGrid, registries);

            vaultList.add(vTag);
        }
        tag.put("vaults", vaultList);
        return tag;
    }

    public static ArchivarData load(CompoundTag tag, HolderLookup.Provider registries) {
        ArchivarData data = new ArchivarData();
        ListTag vaultList = tag.getList("vaults", Tag.TAG_COMPOUND);
        for (int i = 0; i < vaultList.size(); i++) {
            CompoundTag vTag = vaultList.getCompound(i);
            if (!vTag.hasUUID("owner")) continue;
            UUID owner = vTag.getUUID("owner");
            Vault vault = new Vault();

            // 1. Archiv Items laden
            ListTag itemList = vTag.getList("items", Tag.TAG_COMPOUND);
            for (int j = 0; j < itemList.size(); j++) {
                CompoundTag iTag = itemList.getCompound(j);
                if (iTag.contains("item", Tag.TAG_COMPOUND)) {
                    ItemStack parsed = ItemStack.parseOptional(registries, iTag.getCompound("item"));
                    if (!parsed.isEmpty()) {
                        long count = iTag.getLong("count");
                        vault.items.add(new Entry(parsed, count));
                    }
                }
            }

            // 2. Crafting Grid laden
            ContainerHelper.loadAllItems(vTag, vault.craftingGrid, registries);

            data.vaults.put(owner, vault);
        }
        return data;
    }
}
