package net.archivar.block;

import net.archivar.Archivar;
import net.archivar.storage.ArchivarData;
import net.minecraft.core.BlockPos;
import net.minecraft.core.HolderLookup;
import net.minecraft.core.NonNullList;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.Container;
import net.minecraft.world.ContainerHelper;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.state.BlockState;

import java.util.UUID;

public class StorageInterfaceBlockEntity extends BlockEntity implements Container {
    private UUID ownerUuid;
    private final NonNullList<ItemStack> buffer = NonNullList.withSize(9, ItemStack.EMPTY);

    public StorageInterfaceBlockEntity(BlockPos pos, BlockState state) {
        super(Archivar.STORAGE_INTERFACE_BE, pos, state);
    }

    public void setOwner(UUID owner) {
        this.ownerUuid = owner;
        setChanged();
    }

    public UUID getOwner() {
        return ownerUuid;
    }

    public static void tick(Level level, BlockPos pos, BlockState state, StorageInterfaceBlockEntity be) {
        if (!(level instanceof ServerLevel sl) || be.ownerUuid == null) return;
        ArchivarData data = ArchivarData.get(sl.getServer());
        ArchivarData.Vault vault = data.getVault(be.ownerUuid);

        for (int i = 0; i < be.buffer.size(); i++) {
            ItemStack stack = be.buffer.get(i);
            if (!stack.isEmpty()) {
                vault.insert(stack);
                be.buffer.set(i, ItemStack.EMPTY);
                be.setChanged();
            }
        }
    }

    @Override
    public int getContainerSize() {
        return buffer.size();
    }

    @Override
    public boolean isEmpty() {
        for (ItemStack s : buffer) if (!s.isEmpty()) return false;
        return true;
    }

    @Override
    public ItemStack getItem(int slot) {
        return buffer.get(slot);
    }

    @Override
    public ItemStack removeItem(int slot, int amount) {
        ItemStack res = ContainerHelper.removeItem(buffer, slot, amount);
        setChanged();
        return res;
    }

    @Override
    public ItemStack removeItemNoUpdate(int slot) {
        ItemStack res = ContainerHelper.takeItem(buffer, slot);
        setChanged();
        return res;
    }

    @Override
    public void setItem(int slot, ItemStack stack) {
        buffer.set(slot, stack);
        if (stack.getCount() > getMaxStackSize()) {
            stack.setCount(getMaxStackSize());
        }
        setChanged();
    }

    @Override
    public boolean stillValid(Player player) {
        // Nur Owner darf per Container (Hopper) auf den Buffer zugreifen
        if (ownerUuid == null) return false;
        return ownerUuid.equals(player.getUUID()) && Container.stillValidBlockEntity(this, player);
    }

    @Override
    public void clearContent() {
        buffer.clear();
    }

    @Override
    protected void saveAdditional(CompoundTag tag, HolderLookup.Provider registries) {
        super.saveAdditional(tag, registries);
        if (ownerUuid != null) tag.putUUID("owner", ownerUuid);
        // Buffer NICHT persistieren – ist nur Transit-Puffer für Hopper/Pipes.
        // Items sind bereits im Vault (ArchivarData) gelandet.
    }

    @Override
    protected void loadAdditional(CompoundTag tag, HolderLookup.Provider registries) {
        super.loadAdditional(tag, registries);
        if (tag.hasUUID("owner")) ownerUuid = tag.getUUID("owner");
        // Buffer bleibt leer – keine Duplikation beim Laden.
    }
}
