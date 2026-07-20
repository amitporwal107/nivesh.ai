package ai.nivesh.app.data.repo;

import ai.nivesh.app.data.api.NiveshApi;
import dagger.internal.DaggerGenerated;
import dagger.internal.Factory;
import dagger.internal.QualifierMetadata;
import dagger.internal.ScopeMetadata;
import javax.annotation.processing.Generated;
import javax.inject.Provider;

@ScopeMetadata("javax.inject.Singleton")
@QualifierMetadata
@DaggerGenerated
@Generated(
    value = "dagger.internal.codegen.ComponentProcessor",
    comments = "https://dagger.dev"
)
@SuppressWarnings({
    "unchecked",
    "rawtypes",
    "KotlinInternal",
    "KotlinInternalInJava"
})
public final class SettingsRepository_Factory implements Factory<SettingsRepository> {
  private final Provider<NiveshApi> apiProvider;

  public SettingsRepository_Factory(Provider<NiveshApi> apiProvider) {
    this.apiProvider = apiProvider;
  }

  @Override
  public SettingsRepository get() {
    return newInstance(apiProvider.get());
  }

  public static SettingsRepository_Factory create(Provider<NiveshApi> apiProvider) {
    return new SettingsRepository_Factory(apiProvider);
  }

  public static SettingsRepository newInstance(NiveshApi api) {
    return new SettingsRepository(api);
  }
}
